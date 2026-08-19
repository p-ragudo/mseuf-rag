import asyncio
from typing import Optional
from redisvl.extensions.llmcache import SemanticCache
from redisvl.utils.vectorize import BaseVectorizer

from .base import BaseSemanticCache
from .schemas import CacheEntry, CacheMetadata
from .vectorizer import get_cache_vectorizer


class RedisSemanticCache(BaseSemanticCache):
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        distance_threshold: float = 0.12,
        ttl: int = 604800,  # 7 days in seconds
        index_name: str = "thesis_semantic_cache",
        vectorizer: Optional[BaseVectorizer] = None,
    ):
        self.redis_url = redis_url
        self.distance_threshold = distance_threshold
        self.ttl = ttl
        self.index_name = index_name
        self.vectorizer = vectorizer or get_cache_vectorizer()

        # Explicitly configure SemanticCache with the interchangeable vectorizer
        self._cache = SemanticCache(
            name=self.index_name,
            redis_url=self.redis_url,
            vectorizer=self.vectorizer,
            distance_threshold=self.distance_threshold,
            ttl=self.ttl,
            overwrite=True
        )

    async def get(self, query: str) -> Optional[CacheEntry]:
        try:
            results = await asyncio.to_thread(
                self._cache.check,
                prompt=query,
                num_results=1,
                distance_threshold=self.distance_threshold,
            )
            print(f"\n[DEBUG Cache Check] Query: '{query}' | Raw results from Redis: {results}")

            if results and len(results) > 0:
                raw_hit = results[0]
                metadata_dict = raw_hit.get("metadata", {}) or {}

                return CacheEntry(
                    query=query,
                    response=raw_hit.get("response", ""),
                    metadata=CacheMetadata(**metadata_dict)
                    if isinstance(metadata_dict, dict)
                    else CacheMetadata(),
                )
        except Exception as e:
            # Fallback smoothly so cache downtime never breaks user queries
            print(f"[Redis Cache] Lookup exception (bypassing): {e}")
        return None

    async def set(
        self,
        query: str,
        response: str,
        metadata: Optional[CacheMetadata] = None,
    ) -> None:
        try:
            meta_payload = metadata.model_dump() if metadata else {}
            await asyncio.to_thread(
                self._cache.store,
                prompt=query,
                response=response,
                metadata=meta_payload,
            )
        except Exception as e:
            print(f"[Redis Cache] Store exception: {e}")

    async def clear(self) -> None:
        try:
            await asyncio.to_thread(self._cache.clear)
        except Exception as e:
            print(f"[Redis Cache] Clear exception: {e}")