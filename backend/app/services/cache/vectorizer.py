import os
from typing import Optional
from redisvl.utils.vectorize import (
    BaseVectorizer,
    HFTextVectorizer,
    OpenAITextVectorizer,
    CohereTextVectorizer,
)
from dotenv import load_dotenv

load_dotenv()

def get_cache_vectorizer(
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
) -> BaseVectorizer:
    """Factory returning the configured RedisVL vectorizer for semantic caching."""
    resolved_provider = (
        provider
        or os.getenv("EMBEDDING_PROVIDER", "huggingface")
    ).lower()

    if resolved_provider == "openai":
        return OpenAITextVectorizer(
            model=model_name or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            api_config={"api_key": os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")},
        )
    elif resolved_provider == "cohere":
        return CohereTextVectorizer(
            model=model_name or os.getenv("EMBEDDING_MODEL", "embed-english-v3.0"),
            api_config={"api_key": os.getenv("COHERE_API_KEY")},
        )
    else:
        # Default: Lightweight local model (384 dimensions, runs locally on CPU)
        return HFTextVectorizer(
            model=model_name or os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        )