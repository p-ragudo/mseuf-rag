import asyncio
import json
import re
from typing import List
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

    # Handle standard JSON objects or lists
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


def parse_questions_fallback(raw_text: str) -> List[str]:
    """Fallback parser if JSON is incomplete or slightly truncated."""
    if raw_text.strip() == "[]":
        return []
    matches = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', raw_text)
    return [
        m
        for m in matches
        if m.lower() not in ("questions", "id", "tags", "content") and len(m) > 10
    ]


class GeminiQuestionGenerator(BaseQuestionGenerator):
    def __init__(self, model_name: str = "gemini-3.1-flash-lite", temperature: float = 0.2):
        self.model_name = model_name
        self.temperature = temperature

        api_key = settings.llm_qgen_api_key
        if not api_key:
            raise ValueError("No API key found. Please set LLM_API_KEY in your .env file.")

        self.client = genai.Client(api_key=api_key)

    async def generate_questions(self, chunk: RawChunk) -> List[GeneratedQuestion]:
        tags_str = ", ".join(chunk.tags) if chunk.tags else "N/A"

        prompt = (
            f"Page Title: {chunk.title.strip() or 'N/A'}\n"
            f"Tags/Entities: {tags_str}\n"
            f"Source URL: {chunk.source_url.strip() or 'N/A'}\n\n"
            f"Content:\n{chunk.content.strip()}"
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
                        max_output_tokens=1500,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )
                break
            except Exception as e:
                err_text = str(e)
                # Catch both client-side quota limits (429) and upstream server spikes (503)
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
                        f"[Gemini Retry] Error on chunk {chunk.id} ({err_text[:80]}...). "
                        f"Retrying in {wait_sec:.1f}s..."
                    )
                    await asyncio.sleep(wait_sec)
                else:
                    raise e

        raw_text = response.text or "" if response else ""
        json_str = extract_clean_json(raw_text)
        question_list: List[str] = []

        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict) and "questions" in parsed:
                question_list = parsed["questions"]
            elif isinstance(parsed, list):
                question_list = parsed
        except Exception:
            question_list = parse_questions_fallback(raw_text)

        # An empty list is valid: it signals the passage had no substantive content
        if not question_list:
            return []

        questions: List[GeneratedQuestion] = []
        for text in question_list:
            clean_text = str(text).strip()
            if clean_text:
                question_id = generate_question_id(chunk_id=chunk.id, question=clean_text)
                questions.append(
                    GeneratedQuestion(
                        id=question_id,
                        chunk_id=chunk.id,
                        content=clean_text,
                        tags=chunk.tags,
                    )
                )

        return questions