from google import genai
from google.genai import types

from app.core.config import settings
from .base_qa import BaseQASynthesizer
from .schema import QARequest, QAResponse
from .sys_instructions import build_system_instruction


class GeminiQASynthesizer(BaseQASynthesizer):
    def __init__(self, model_name: str = "gemini-2.5-flash", temperature: float = 0.3):
        self.model_name = model_name
        self.temperature = temperature

        api_key = getattr(settings, "llm_qa_api_key", None) or settings.llm_qa_api_key
        if not api_key:
            raise ValueError("No API key found. Please set LLM_API_KEY or QA_LLM_API_KEY in your .env file.")

        self.client = genai.Client(api_key=api_key)

    async def generate_answer(self, request: QARequest, org_name: str = "the institution") -> QAResponse:
        context_blocks = []
        sources = []

        for idx, item in enumerate(request.contexts, start=1):
            title = item.title.strip() or "Untitled"
            url = item.source_url.strip() if item.source_url else "N/A"
            location_tag = f" [Branch/Entity: {item.campus.upper()}]" if item.campus else ""
            context_blocks.append(
                f"--- Document [{idx}]{location_tag} ---\n"
                f"Title: {title}\n"
                f"Source: {url}\n"
                f"Content:\n{item.content.strip()}"
            )
            if item.source_url and item.source_url not in sources:
                sources.append(item.source_url)

        context_str = "\n\n".join(context_blocks) if context_blocks else "No context provided."

        prompt = (
            f"Context Documents:\n{context_str}\n\n"
            f"User Question: {request.query.strip()}\n\n"
            f"Answer:"
        )

        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=build_system_instruction(org_name),
                temperature=self.temperature,
                max_output_tokens=1024,
            ),
        )

        return QAResponse(
            answer=response.text.strip(),
            sources=sources,
        )