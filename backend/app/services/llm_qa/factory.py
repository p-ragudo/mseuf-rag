from .base_qa import BaseQASynthesizer
from .gemini_provider import GeminiQASynthesizer
from app.core.config import settings

def get_qa_synthesizer(provider: str = None) -> BaseQASynthesizer:
    # Allows overriding QA-specific provider/model in settings independently of qgen
    provider = provider or getattr(settings, "qa_llm_provider", settings.llm_provider).lower()
    model = getattr(settings, "qa_llm_model", settings.llm_model)

    if provider == "gemini":
        return GeminiQASynthesizer(model_name=model)

    # Future providers (e.g. OpenAI, Ollama, Groq) can be added here
    # elif provider in ("openai", "groq"):
    #     return OpenAIQASynthesizer(model_name=model)

    raise ValueError(f"Unsupported QA LLM provider: {provider}")