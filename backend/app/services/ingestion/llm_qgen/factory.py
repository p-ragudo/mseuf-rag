import os
from app.services.ingestion.llm_qgen.base import BaseQuestionGenerator
from app.services.ingestion.llm_qgen.gemini_provider import GeminiQuestionGenerator
# from app.services.llm_qgen.openai_provider import OpenAICompatibleQuestionGenerator

def get_question_generator(provider: str = None) -> BaseQuestionGenerator:
    provider = provider or os.getenv("LLM_PROVIDER", "gemini").lower()

    if provider == "gemini":
        return GeminiQuestionGenerator(model_name=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"))
    # elif provider in ("openai", "openrouter", "vllm", "ollama"):
    #     return OpenAICompatibleQuestionGenerator(model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

    raise ValueError(f"Unsupported LLM provider: {provider}")