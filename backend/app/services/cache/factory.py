import os
from .base import BaseSemanticCache
from .redis_cache import RedisSemanticCache
from .in_memory_cache import InMemorySemanticCache
from .vectorizer import get_cache_vectorizer
from dotenv import load_dotenv

load_dotenv()


def get_semantic_cache() -> BaseSemanticCache:
    provider = os.getenv("SEMANTIC_CACHE_PROVIDER", "redis").lower()

    if provider == "redis":
        url = os.getenv("SEMANTIC_CACHE_URL")
        print(f"\n[DEBUG] Raw SEMANTIC_CACHE_URL from os.getenv: {repr(url)}\n")

        if not url:
            raise ValueError(
                "SEMANTIC_CACHE_URL resolved to None or empty. "
                "Check if .env is in the current working directory."
            )
        
        return RedisSemanticCache(
            redis_url=os.getenv("SEMANTIC_CACHE_URL", "redis://localhost:6379"),
            distance_threshold=float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.12")),
            ttl=int(os.getenv("SEMANTIC_CACHE_TTL_SECONDS", "604800")),
            index_name=os.getenv("SEMANTIC_CACHE_INDEX_NAME", "thesis_semantic_cache"),
            vectorizer=get_cache_vectorizer(),
        )
    elif provider in ("memory", "mock", "test"):
        return InMemorySemanticCache()
    else:
        raise ValueError(f"Unknown SEMANTIC_CACHE_PROVIDER: '{provider}'")


# Single global instance for the application
semantic_cache = get_semantic_cache()