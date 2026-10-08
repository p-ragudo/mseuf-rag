from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from .schema import SearchResult, VectorPoint


class BaseVectorDB(ABC):
    @abstractmethod
    async def create_collection_if_not_exists(
        self,
        collection_name: str,
        dense_vector_size: Optional[int] = None,
        distance: str = "Cosine",
        enable_quantization: Optional[bool] = None,
    ) -> None:
        """Creates a collection if it does not exist with vector parameters and indexing."""
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
        using_vector_name: str = "question_dense",
        rescore: Optional[bool] = None,
        oversampling: Optional[float] = None,
    ) -> List[SearchResult]:
        pass

    @abstractmethod
    async def search_sparse(
        self,
        collection_name: str,
        sparse_indices: List[int],
        sparse_values: List[float],
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        with_payload: bool = True,
        using_vector_name: str = "chunk_sparse",
    ) -> List[SearchResult]:
        pass

    @abstractmethod
    async def delete_points(
        self,
        collection_name: str,
        filters: Dict[str, Any],
        must_not: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Deletes points matching `filters` (and not matching `must_not`). `filters` MUST contain group_id."""
        pass

    @abstractmethod
    async def close(self) -> None:
        pass