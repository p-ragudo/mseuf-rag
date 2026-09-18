from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from .schema import SearchResult, VectorPoint


class BaseVectorDB(ABC):
    @abstractmethod
    @abstractmethod
    async def create_collection_if_not_exists(
        self,
        collection_name: str,
        vector_size: Optional[int] = None,
        distance: str = "Cosine",
    ) -> None:
        """Creates a collection if it does not exist.
        
        If vector_size is None, creates a payload-only collection without vector storage.
        """
        pass

    @abstractmethod
    async def upsert_points(
        self, collection_name: str, points: List[VectorPoint]
    ) -> None:
        pass

    @abstractmethod
    async def upsert_payload_only(
        self,
        collection_name: str,
        records: List[Dict[str, Any]],
        id_key: str = "id",
    ) -> None:
        """Stores records as payload-only without computing or storing dense vectors."""
        pass

    @abstractmethod
    async def search(
        self,
        collection_name: str,
        query_vector: Optional[List[float]] = None,
        query_text: Optional[str] = None,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        with_payload: bool = True,
    ) -> List[SearchResult]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass