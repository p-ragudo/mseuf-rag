from typing import List, Optional
from redisvl.extensions.llmcache import SemanticCache
from redisvl.utils.vectorize import CustomVectorizer

from .base import BaseSemanticCache
from .schemas import CacheEntry, CacheMetadata


class RedisSemanticCache(BaseSemanticCache):
    def __init__(
        self,
        redis_url: str,
        distance_threshold: float,
        ttl: int,
        index_name: str,
        dim: int
    ) -> None:
        self.redis_url = redis_url
        self.distance_threshold = distance_threshold
        self.ttl = ttl
        self.index_name = index_name
        self.dim = dim

        # Dummy function satisfies RedisVL without importing torch or sentence-transformers
        dummy_vectorizer = CustomVectorizer(
            embed=lambda text, **kwargs: [0.0] * self.dim
        )

        # SemanticCache handles vector comparison (range query / cosine distance)
        self._cache = SemanticCache(
            name=self.index_name,
            redis_url=self.redis_url,
            distance_threshold=self.distance_threshold,
            ttl=self.ttl,
            overwrite=True,
            dim=self.dim,
            vectorizer=dummy_vectorizer,  # Prevents defaulting to HFTextVectorizer / torch
        )

    async def get(self, vector: List[float]) -> Optional[CacheEntry]:
        try:
            # acheck uses the pre-computed vector directly without calling an internal vectorizer
            results = await self._cache.acheck(
                vector=vector,
                num_results=1,
                distance_threshold=self.distance_threshold,
            )

            if results and len(results) > 0:
                raw_hit = results[0]
                metadata_dict = raw_hit.get("metadata", {}) or {}

                return CacheEntry(
                    query=raw_hit.get("prompt", ""),
                    response=raw_hit.get("response", ""),
                    metadata=CacheMetadata(**metadata_dict)
                    if isinstance(metadata_dict, dict)
                    else CacheMetadata(),
                )
        except Exception as e:
            print(f"[Redis Cache] Lookup exception (bypassing): {e}")
        return None

    async def set(
        self,
        query: str,
        vector: List[float],
        response: str,
        metadata: Optional[CacheMetadata] = None,
    ) -> None:
        try:
            meta_payload = metadata.model_dump() if metadata else {}
            # astore persists the vector alongside prompt, response, and metadata
            await self._cache.astore(
                prompt=query,
                vector=vector,
                response=response,
                metadata=meta_payload,
            )
        except Exception as e:
            print(f"[Redis Cache] Store exception: {e}")

    async def clear(self) -> None:
        try:
            await self._cache.aclear()
        except Exception as e:
            print(f"[Redis Cache] Clear exception: {e}")