from typing import List, Optional
from .base_vdb import BaseVectorDB
from .schema import VectorPoint, SearchResult


class VectorDatabaseService:
    """High-level domain service for vector operations.
    
    Accepts any concrete BaseVectorDB provider via Dependency Injection.
    """
    def __init__(self, db: BaseVectorDB):
        self.db = db

    async def ensure_collection(self, collection_name: str, vector_dim: int) -> None:
        await self.db.create_collection_if_not_exists(
            collection_name=collection_name,
            vector_size=vector_dim
        )

    async def save_question_vectors(
        self, 
        collection_name: str, 
        points: List[VectorPoint]
    ) -> None:
        """Batched upsert for question dense vectors."""
        if not points:
            return
        await self.db.upsert_points(collection_name=collection_name, points=points)

    async def find_similar_questions(
        self,
        collection_name: str,
        query_vector: List[float],
        top_k: int = 5,
        tag_filters: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """Retrieves top-k matching question vectors with optional tag filtering."""
        filters = {"tags": tag_filters} if tag_filters else None
        return await self.db.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=top_k,
            filters=filters,
            with_payload=True
        )