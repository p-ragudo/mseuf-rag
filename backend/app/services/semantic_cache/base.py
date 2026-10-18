from abc import ABC, abstractmethod
from typing import List, Optional
from .schemas import CacheEntry, CacheMetadata


class BaseSemanticCache(ABC):
    """Abstract Base Class for semantic caching services using pre-computed embeddings."""

    @abstractmethod
    async def get(
        self,
        vector: List[float],
        org_id: int | str,
    ) -> Optional[CacheEntry]:
        """Queries the semantic cache for a specific tenant using a pre-computed vector."""
        pass

    @abstractmethod
    async def set(
        self,
        query: str,
        vector: List[float],
        response: str,
        org_id: int | str,
        metadata: Optional[CacheMetadata] = None,
    ) -> None:
        """Stores query, pre-computed vector, response, tenant isolation tag, and metadata."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clears all records in the cache index."""
        pass