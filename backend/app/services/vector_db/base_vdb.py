from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from .schema import SearchResult, VectorPoint


class BaseVectorDB(ABC):
    @abstractmethod
    async def create_collection_if_not_exists(
        self, collection_name: str, vector_size: int
    ) -> None:
        pass

    @abstractmethod
    async def upsert_points(
        self, collection_name: str, points: List[VectorPoint]
    ) -> None:
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