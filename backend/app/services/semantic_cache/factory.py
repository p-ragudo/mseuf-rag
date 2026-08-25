import os
from dotenv import load_dotenv
from .base import BaseSemanticCache
from .redis_cache import RedisSemanticCache
from .in_memory_cache import InMemorySemanticCache

load_dotenv()


def get_semantic_cache() -> BaseSemanticCache:
    provider = os.getenv("SEMANTIC_CACHE_PROVIDER")

    if not provider:
        raise ValueError("Environment variable 'SEMANTIC_CACHE_PROVIDER' is required.")

    provider = provider.lower()

    if provider == "redis":
        url = os.getenv("SEMANTIC_CACHE_URL")
        if not url:
            raise ValueError("SEMANTIC_CACHE_URL environment variable is required for redis provider.")

        threshold = os.getenv("SEMANTIC_CACHE_THRESHOLD")
        if not threshold:
            raise ValueError("SEMANTIC_CACHE_THRESHOLD environment variable is required.")

        ttl = os.getenv("SEMANTIC_CACHE_TTL_SECONDS")
        if not ttl:
            raise ValueError("SEMANTIC_CACHE_TTL_SECONDS environment variable is required.")

        index_name = os.getenv("SEMANTIC_CACHE_INDEX_NAME")
        if not index_name:
            raise ValueError("SEMANTIC_CACHE_INDEX_NAME environment variable is required.")

        return RedisSemanticCache(
            redis_url=url,
            distance_threshold=float(threshold),
            ttl=int(ttl),
            index_name=index_name,
        )

    elif provider in ("memory", "mock", "test"):
        threshold = float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.12"))
        return InMemorySemanticCache(distance_threshold=threshold)

    else:
        raise ValueError(f"Unknown SEMANTIC_CACHE_PROVIDER: '{provider}'")