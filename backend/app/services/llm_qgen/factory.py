from .base_qgen import BaseQuestionGenerator
from .gemini_provider import GeminiQuestionGenerator
from app.core.config import settings

def get_question_generator(provider: str = None) -> BaseQuestionGenerator:
    provider = provider or settings.llm_provider.lower()
    model = settings.llm_model

    if provider == "gemini":
        return GeminiQuestionGenerator(model_name=model)
    
    # add some more here if ever
    # elif provider in ("openai", "openrouter", "vllm", "ollama"):
    #     return OpenAICompatibleQuestionGenerator(model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

    raise ValueError(f"Unsupported LLM provider: {provider}")