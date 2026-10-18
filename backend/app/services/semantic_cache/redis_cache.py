from typing import List, Optional
from redisvl.extensions.llmcache import SemanticCache
from redisvl.query.filter import Tag
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
        dim: int,
    ) -> None:
        self.redis_url = redis_url
        self.distance_threshold = distance_threshold
        self.ttl = ttl
        self.index_name = index_name
        self.dim = dim
        self._cache: Optional[SemanticCache] = None

        # Satisfies RedisVL vectorizer requirement without external downloads
        dummy_vectorizer = CustomVectorizer(
            embed=lambda text, **kwargs: [0.0] * self.dim
        )

        try:
            self._cache = SemanticCache(
                name=self.index_name,
                redis_url=self.redis_url,
                distance_threshold=self.distance_threshold,
                ttl=self.ttl,
                overwrite=True,
                dim=self.dim,
                vectorizer=dummy_vectorizer,
                # Multi-tenancy filterable tag field
                filterable_fields=[{"name": "org_id", "type": "tag"}],
            )
        except Exception as e:
            print(f"[Redis Cache] Initialization warning (cache disabled/bypassed): {e}")

    async def get(
        self,
        vector: List[float],
        org_id: int | str,
    ) -> Optional[CacheEntry]:
        if not self._cache:
            return None
        try:
            tenant_tag = Tag("org_id") == str(org_id)

            results = await self._cache.acheck(
                vector=vector,
                num_results=1,
                distance_threshold=self.distance_threshold,
                filter_expression=tenant_tag,
            )

            if results and len(results) > 0:
                raw_hit = results[0]
                metadata_dict = raw_hit.get("metadata", {}) or {}

                return CacheEntry(
                    query=raw_hit.get("prompt", ""),
                    response=raw_hit.get("response", ""),
                    metadata=(
                        CacheMetadata(**metadata_dict)
                        if isinstance(metadata_dict, dict)
                        else CacheMetadata()
                    ),
                )
        except Exception as e:
            print(f"[Redis Cache] Lookup exception (bypassing): {e}")
        return None

    async def set(
        self,
        query: str,
        vector: List[float],
        response: str,
        org_id: int | str,
        metadata: Optional[CacheMetadata] = None,
    ) -> None:
        if not self._cache:
            return
        try:
            meta_payload = metadata.model_dump() if metadata else {}
            await self._cache.astore(
                prompt=query,
                vector=vector,
                response=response,
                filters={"org_id": str(org_id)},
                metadata=meta_payload,
            )
        except Exception as e:
            print(f"[Redis Cache] Store exception: {e}")

    async def clear(self) -> None:
        if not self._cache:
            return
        try:
            await self._cache.aclear()
        except Exception as e:
            print(f"[Redis Cache] Clear exception: {e}")