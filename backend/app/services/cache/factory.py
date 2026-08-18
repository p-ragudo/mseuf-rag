import os
from .base import BaseSemanticCache
from .redis_cache import RedisSemanticCache
from .in_memory_cache import InMemorySemanticCache


def get_semantic_cache() -> BaseSemanticCache:
    provider = os.getenv("SEMANTIC_CACHE_PROVIDER", "redis").lower()

    if provider == "redis":
        return RedisSemanticCache(
            redis_url=os.getenv("SEMANTIC_CACHE_URL", "redis://localhost:6379"),
            distance_threshold=float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.12")),
            ttl=int(os.getenv("SEMANTIC_CACHE_TTL_SECONDS", "604800")),
        )
    elif provider in ("memory", "mock", "test"):
        return InMemorySemanticCache()
    else:
        raise ValueError(f"Unknown SEMANTIC_CACHE_PROVIDER: '{provider}'")


# Single global instance for the application
semantic_cache = get_semantic_cache()