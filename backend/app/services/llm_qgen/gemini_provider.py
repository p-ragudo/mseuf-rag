import asyncio
import json
import re
from typing import List, Dict
from google import genai
from google.genai import types

from app.core.config import settings
from .base_qgen import BaseQuestionGenerator
from .schema import RawChunk, GeneratedQuestion
from ...utils.uuid_generator import generate_question_id
from .sys_instructions import SYSTEM_INSTRUCTION


def extract_clean_json(text: str) -> str:
    """Extract strictly from the first '{' to the last '}' or '[' to ']' and strip backticks."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)

    start_brace = cleaned.find("{")
    end_brace = cleaned.rfind("}")
    start_bracket = cleaned.find("[")
    end_bracket = cleaned.rfind("]")

    if start_bracket != -1 and (start_brace == -1 or start_bracket < start_brace):
        if end_bracket != -1 and end_bracket > start_bracket:
            return cleaned[start_bracket : end_bracket + 1]

    if start_brace != -1 and end_brace != -1 and end_brace > start_brace:
        return cleaned[start_brace : end_brace + 1]

    return cleaned.strip()


class GeminiQuestionGenerator(BaseQuestionGenerator):
    def __init__(self, model_name: str = "gemini-2.5-flash", temperature: float = 0.2):
        self.model_name = model_name
        self.temperature = temperature

        api_key = settings.llm_qgen_api_key
        if not api_key:
            raise ValueError("No API key found. Please set LLM_API_KEY in your .env file.")

        self.client = genai.Client(api_key=api_key)

    async def generate_questions(self, chunk: RawChunk) -> List[GeneratedQuestion]:
        """Single-chunk backward compatibility."""
        batch_res = await self.generate_questions_batch([chunk])
        return batch_res.get(chunk.id, [])

    async def generate_questions_batch(self, chunks: List[RawChunk]) -> Dict[str, List[GeneratedQuestion]]:
        """Batches multiple chunks into a single LLM prompt to save cost and quota."""
        if not chunks:
            return {}

        formatted_chunks = []
        for c in chunks:
            tags_str = ", ".join(c.tags) if c.tags else "N/A"
            formatted_chunks.append(
                f"--- START CHUNK ID: {c.id} ---\n"
                f"Title: {c.title.strip() or 'N/A'}\n"
                f"Source URL: {c.source_url.strip() or 'N/A'}\n"
                f"Tags: {tags_str}\n"
                f"Content:\n{c.content.strip()}\n"
                f"--- END CHUNK ID: {c.id} ---"
            )

        prompt = (
            "Analyze each of the following content chunks independently.\n"
            "For each chunk, generate 3 to 5 realistic, concrete questions that it directly answers.\n"
            "If a chunk lacks substantive content (e.g. navigation menu, cookie policy, generic announcement), map its ID to an empty list [].\n\n"
            "Return a strictly valid JSON object where keys are the CHUNK IDs and values are arrays of strings:\n"
            "{\n"
            '  "<chunk_id>": ["question 1", "question 2", ...]\n'
            "}\n\n"
            f"{chr(10).join(formatted_chunks)}"
        )

        max_retries = 5
        base_delay = 5.0
        response = None

        for attempt in range(max_retries):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        temperature=self.temperature,
                        max_output_tokens=6000,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )
                break
            except Exception as e:
                err_text = str(e)
                retryable_errors = (
                    "429",
                    "RESOURCE_EXHAUSTED",
                    "503",
                    "UNAVAILABLE",
                    "high demand",
                )
                if any(err in err_text for err in retryable_errors) and attempt < max_retries - 1:
                    wait_sec = base_delay * (2 ** attempt)
                    print(
                        f"[Gemini QGen Retry] Rate/capacity hit on batch of {len(chunks)} chunks. "
                        f"Retrying in {wait_sec:.1f}s..."
                    )
                    await asyncio.sleep(wait_sec)
                else:
                    raise e

        raw_text = response.text or "" if response else "{}"
        json_str = extract_clean_json(raw_text)

        parsed_map: Dict[str, List[str]] = {}
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict):
                if "chunks" in parsed and isinstance(parsed["chunks"], dict):
                    parsed_map = parsed["chunks"]
                else:
                    parsed_map = parsed
        except Exception as e:
            print(f"[QGen Batch Parse Error]: {e}. Raw response: {raw_text[:200]}")
            parsed_map = {}

        output_map: Dict[str, List[GeneratedQuestion]] = {}
        for c in chunks:
            q_strings = parsed_map.get(str(c.id), [])
            chunk_questions: List[GeneratedQuestion] = []
            if isinstance(q_strings, list):
                for q_text in q_strings:
                    clean_text = str(q_text).strip()
                    if clean_text:
                        q_id = generate_question_id(chunk_id=c.id, question=clean_text)
                        chunk_questions.append(
                            GeneratedQuestion(
                                id=q_id,
                                chunk_id=c.id,
                                content=clean_text,
                                tags=c.tags,
                            )
                        )
            output_map[c.id] = chunk_questions

        return output_map