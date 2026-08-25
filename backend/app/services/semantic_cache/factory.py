from .base import BaseSemanticCache
from .redis_cache import RedisSemanticCache
from .in_memory_cache import InMemorySemanticCache
from app.core.config import settings

def get_semantic_cache() -> BaseSemanticCache:
    provider = settings.semantic_cache_provider

    if not provider:
        raise ValueError("Environment variable 'SEMANTIC_CACHE_PROVIDER' is required.")

    provider = provider.lower()

    if provider == "redis":
        url = settings.semantic_cache_url
        if not url:
            raise ValueError("SEMANTIC_CACHE_URL environment variable is required for redis provider.")

        threshold = settings.semantic_cache_threshold
        if not threshold:
            raise ValueError("SEMANTIC_CACHE_THRESHOLD environment variable is required.")

        ttl = settings.semantic_cache_ttl_seconds
        if not ttl:
            raise ValueError("SEMANTIC_CACHE_TTL_SECONDS environment variable is required.")

        index_name = settings.semantic_cache_index_name
        if not index_name:
            raise ValueError("SEMANTIC_CACHE_INDEX_NAME environment variable is required.")

        return RedisSemanticCache(
            redis_url=url,
            distance_threshold=float(threshold),
            ttl=int(ttl),
            index_name=index_name,
        )

    elif provider in ("memory", "mock", "test"):
        threshold = settings.semantic_cache_threshold
        return InMemorySemanticCache(distance_threshold=threshold)

    else:
        raise ValueError(f"Unknown SEMANTIC_CACHE_PROVIDER: '{provider}'")