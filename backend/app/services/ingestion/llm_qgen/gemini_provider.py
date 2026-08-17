from google import genai
from google.genai import types
from app.services.ingestion.llm_qgen.base import BaseQuestionGenerator
from app.services.ingestion.llm_qgen.qgen import RawChunk, GeneratedQuestionSet
from app.services.ingestion.llm_qgen.sys_instructions import SYSTEM_INSTRUCTION

from dotenv import load_dotenv

load_dotenv()

class GeminiQuestionGenerator(BaseQuestionGenerator):
    def __init__(self, model_name: str = "gemini-3.1-flash-lite", temperature: float = 0.3):
        self.model_name = model_name
        self.temperature = temperature
        self.client = genai.Client()

    async def generate_questions(self, chunk: RawChunk) -> GeneratedQuestionSet:
        prompt = (
            f"Page Title: {chunk.title}\n"
            f"URL: {chunk.source_url}\n\n"
            f"Content:\n{chunk.content}"
        )
        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=GeneratedQuestionSet,
                temperature=self.temperature,
            ),
        )
        # response.parsed is automatically populated as a GeneratedQuestionSet instance
        if hasattr(response, "parsed") and response.parsed:
            return response.parsed
        return GeneratedQuestionSet.model_validate_json(response.text)