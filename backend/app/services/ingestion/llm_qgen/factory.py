import os
from .base_qgen import BaseQuestionGenerator
from .gemini_provider import GeminiQuestionGenerator

def get_question_generator(provider: str = None) -> BaseQuestionGenerator:
    provider = provider or os.getenv("LLM_PROVIDER", "gemini").lower()

    if provider == "gemini":
        model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
        return GeminiQuestionGenerator(model_name=model)
    
    # add some more here if ever
    # elif provider in ("openai", "openrouter", "vllm", "ollama"):
    #     return OpenAICompatibleQuestionGenerator(model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

    raise ValueError(f"Unsupported LLM provider: {provider}")