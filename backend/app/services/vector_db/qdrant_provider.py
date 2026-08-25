from typing import Any, Dict, List, Optional
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as rest_models
from app.core.config import settings

from .base import BaseVectorDB
from .schema import VectorPoint, SearchResult

class QdrantVectorDB(BaseVectorDB):
    def __init__(self, client: Optional[AsyncQdrantClient] = None):
        if client:
            self.client = client
            return

        is_dev = settings.use_test_qdrant_db.lower() in ("true", "1", "yes")

        if is_dev:
            cluster_endpoint = settings.test_qdrant_cluster_endpoint
            api_key = settings.test_qdrant_api_key
        else:
            cluster_endpoint = settings.qdrant_cluster_endpoint
            api_key = settings.qdrant_api_key

        if not cluster_endpoint:
            env_var = "TEST_QDRANT_CLUSTER_ENDPOINT" if is_dev else "QDRANT_CLUSTER_ENDPOINT"
            raise ValueError(f"{env_var} is not configured in the environment.")

        self.client = AsyncQdrantClient(url=cluster_endpoint, api_key=api_key)

    async def create_collection_if_not_exists(
        self, 
        collection_name: str, 
        vector_size: Optional[int] = None, 
        distance: str = "Cosine"
    ) -> None:
        collections = await self.client.get_collections()
        existing_names = {col.name for col in collections.collections}

        if collection_name not in existing_names:
            distance_map = {
                "Cosine": rest_models.Distance.COSINE,
                "Dot": rest_models.Distance.DOT,
                "Euclid": rest_models.Distance.EUCLID,
            }
            selected_distance = distance_map.get(distance, rest_models.Distance.COSINE)

            # Pass {} to vectors_config for unvectorized payload-only storage
            vectors_config = (
                rest_models.VectorParams(
                    size=vector_size,
                    distance=selected_distance,
                )
                if vector_size is not None
                else {}
            )

            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=vectors_config,
            )

    async def upsert_points(
        self, 
        collection_name: str, 
        points: List[VectorPoint]
    ) -> None:
        qdrant_points = [
            rest_models.PointStruct(
                id=p.id,
                vector=p.vector,
                payload=p.payload
            )
            for p in points
        ]
        await self.client.upsert(
            collection_name=collection_name,
            points=qdrant_points,
            wait=True
        )

    async def upsert_payload_only(
        self,
        collection_name: str,
        records: List[Dict[str, Any]],
        id_key: str = "id",
    ) -> None:
        """Upserts records directly as payloads without vector generation.

        Args:
            collection_name: Target collection.
            records: List of dictionaries to store as payload data.
            id_key: Key inside each record to use as point ID (falls back to UUID).
        """
        qdrant_points: List[rest_models.PointStruct] = []

        for record in records:
            point_id = record.get(id_key)
            if not point_id:
                raise ValueError(
                    f"Record is missing required identifier key '{id_key}': {record}"
                )

            payload = {k: v for k, v in record.items() if k != id_key}

            qdrant_points.append(
                rest_models.PointStruct(
                    id=point_id,
                    vector={},
                    payload=payload,
                )
            )

        await self.client.upsert(
            collection_name=collection_name,
            points=qdrant_points,
            wait=True,
        )

    async def search(
        self,
        collection_name: str,
        query_vector: List[float],
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        with_payload: bool = True,
    ) -> List[SearchResult]:
        qdrant_filter = None
        if filters:
            conditions = []
            for key, val in filters.items():
                if isinstance(val, list):
                    # Matches any tag in a list
                    conditions.append(
                        rest_models.FieldCondition(
                            key=key,
                            match=rest_models.MatchAny(any=val)
                        )
                    )
                else:
                    conditions.append(
                        rest_models.FieldCondition(
                            key=key,
                            match=rest_models.MatchValue(value=val)
                        )
                    )
            qdrant_filter = rest_models.Filter(must=conditions)

        response = await self.client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit,
            query_filter=qdrant_filter,
            with_payload=with_payload,
        )

        return [
            SearchResult(
                id=str(hit.id),
                score=hit.score,
                payload=hit.payload or {}
            )
            for hit in response.points
        ]