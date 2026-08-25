from abc import ABC, abstractmethod
from typing import List, Optional
from .schemas import CacheEntry, CacheMetadata


class BaseSemanticCache(ABC):
    """Abstract Base Class for semantic caching services using pre-computed embeddings."""

    @abstractmethod
    async def get(self, vector: List[float]) -> Optional[CacheEntry]:
        """Queries the semantic cache using a pre-computed vector.
        
        Returns a validated CacheEntry if similarity is within threshold, else None.
        """
        pass

    @abstractmethod
    async def set(
        self,
        query: str,
        vector: List[float],
        response: str,
        metadata: Optional[CacheMetadata] = None,
    ) -> None:
        """Stores query, pre-computed vector, response, and metadata in the cache."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clears all records in the cache index."""
        pass