import json
import re
from typing import List
from google import genai
from google.genai import types

from app.core.config import settings
from .base_qgen import BaseQuestionGenerator
from .schema import RawChunk, GeneratedQuestion, GeneratedQuestionSet
from ...utils.uuid_generator import generate_question_id
from .sys_instructions import SYSTEM_INSTRUCTION


def extract_clean_json(text: str) -> str:
    """Extract strictly from the first '{' to the last '}' and strip backticks."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1]

    return cleaned.strip()


def parse_questions_fallback(raw_text: str) -> List[str]:
    """Fallback parser if JSON is incomplete or slightly truncated."""
    # Try finding quoted strings inside questions array
    matches = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', raw_text)
    # Filter out common keys
    return [m for m in matches if m.lower() not in ("questions", "id", "tags", "content") and len(m) > 10]


class GeminiQuestionGenerator(BaseQuestionGenerator):
    def __init__(self, model_name: str = "gemini-3.1-flash-lite", temperature: float = 0.2):
        self.model_name = model_name
        self.temperature = temperature

        api_key = settings.llm_api_key
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

        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                temperature=self.temperature,
                max_output_tokens=1500,
            ),
        )

        raw_text = response.text or ""
        json_str = extract_clean_json(raw_text)
        question_list: List[str] = []

        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict) and "questions" in parsed:
                question_list = parsed["questions"]
            elif isinstance(parsed, list):
                question_list = parsed
        except Exception:
            # Fallback if string got cut off near the end
            question_list = parse_questions_fallback(raw_text)

        if not question_list:
            raise ValueError(f"Could not parse questions from response: {raw_text[:200]}")

        # Build normalized GeneratedQuestion objects
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