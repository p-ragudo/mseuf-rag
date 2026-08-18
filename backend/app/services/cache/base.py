from abc import ABC, abstractmethod
from typing import Optional
from .schemas import CacheEntry, CacheMetadata


class BaseSemanticCache(ABC):
    """Abstract Base Class for semantic caching services."""

    @abstractmethod
    async def get(self, query: str) -> Optional[CacheEntry]:
        """
        Queries the semantic cache.
        Returns a validated CacheEntry if similarity is within threshold, else None.
        """
        pass

    @abstractmethod
    async def set(
        self,
        query: str,
        response: str,
        metadata: Optional[CacheMetadata] = None,
    ) -> None:
        """Stores query, response, and metadata in the cache."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clears all records in the cache index."""
        pass