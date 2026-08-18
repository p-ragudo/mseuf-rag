from typing import List
from google import genai
from google.genai import types
from dotenv import load_dotenv

from .base_qgen import BaseQuestionGenerator
from ..schema import RawChunk, GeneratedQuestion, GeneratedQuestionSet
from ....utils.uuid_generator import generate_question_id
from .sys_instructions import SYSTEM_INSTRUCTION

load_dotenv()

class GeminiQuestionGenerator(BaseQuestionGenerator):
    def __init__(self, model_name: str = "gemini-3.1-flash-lite", temperature: float = 0.2):
        self.model_name = model_name
        self.temperature = temperature
        self.client = genai.Client()

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
                response_schema=GeneratedQuestionSet,
                temperature=self.temperature,
                max_output_tokens=300,
            ),
        )

        if hasattr(response, "parsed") and response.parsed:
            raw_set = response.parsed
        else:
            raw_set = GeneratedQuestionSet.model_validate_json(response.text)

        # Build normalized GeneratedQuestion objects
        questions: List[GeneratedQuestion] = []
        for idx, text in enumerate(raw_set.questions, start=1):
            clean_text = text.strip()
            if clean_text:
                # Binding to chunk.id guarantees uniqueness across different chunks,
                # while keeping the ID deterministic if you re-run question generation.
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