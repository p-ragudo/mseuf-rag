import asyncio
from typing import Optional
from redisvl.extensions.llmcache import SemanticCache

from .base import BaseSemanticCache
from .schemas import CacheEntry, CacheMetadata


class RedisSemanticCache(BaseSemanticCache):
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        distance_threshold: float = 0.12,
        ttl: int = 604800,  # 7 days in seconds
        index_name: str = "thesis_semantic_cache",
    ):
        self.redis_url = redis_url
        self.distance_threshold = distance_threshold
        self.ttl = ttl
        self.index_name = index_name

        self._cache = SemanticCache(
            name=self.index_name,
            redis_url=self.redis_url,
            distance_threshold=self.distance_threshold,
            ttl=self.ttl,
        )

    async def get(self, query: str) -> Optional[CacheEntry]:
        try:
            results = await asyncio.to_thread(self._cache.check, prompt=query)
            if results and len(results) > 0:
                raw_hit = results[0]
                metadata_dict = raw_hit.get("metadata", {}) or {}
                
                return CacheEntry(
                    query=query,
                    response=raw_hit.get("response", ""),
                    metadata=CacheMetadata(**metadata_dict) if isinstance(metadata_dict, dict) else CacheMetadata(),
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