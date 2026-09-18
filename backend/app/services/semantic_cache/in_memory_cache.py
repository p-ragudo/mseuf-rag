from typing import Dict, Optional
from .base import BaseSemanticCache
from .schemas import CacheEntry, CacheMetadata


class InMemorySemanticCache(BaseSemanticCache):
    """Zero-dependency cache for fast unit tests without needing a running Redis server."""

    def __init__(self):
        self._store: Dict[str, CacheEntry] = {}

    async def get(self, query: str) -> Optional[CacheEntry]:
        normalized = query.strip().lower()
        return self._store.get(normalized)

    async def set(
        self,
        query: str,
        response: str,
        metadata: Optional[CacheMetadata] = None,
    ) -> None:
        normalized = query.strip().lower()
        self._store[normalized] = CacheEntry(
            query=query,
            response=response,
            metadata=metadata or CacheMetadata(),
        )

    async def clear(self) -> None:
        self._store.clear()