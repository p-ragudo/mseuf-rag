from typing import Any, Dict, List, Optional
from qdrant_client import AsyncQdrantClient, models
from app.core.config import settings

from .base import BaseVectorDB
from .schema import SearchResult, VectorPoint

class QdrantCloudInferenceProvider(BaseVectorDB):
    def __init__(
        self,
        client: Optional[AsyncQdrantClient] = None,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None
    ):
        env_model = settings.qdrant_embedding_model
        if not env_model:
            raise ValueError("VECTOR_DB_EMBEDDING_MODEL is not configured in the environment.")

        self.default_model = default_model or env_model

        if client:
            self.client = client
            return

        # Check development flag (handles DEVELOPMENT and DEVELOPEMNT typo)
        use_test_db = settings.use_test_qdrant_db

        embedding_model = (
            settings.vector_db_embedding_model.lower()
        )

        cluster_endpoint = url or (
            settings.test_qdrant_cluster_endpoint
            if use_test_db
            else settings.qdrant_cluster_endpoint
        )
        resolved_api_key = api_key or (
            settings.test_qdrant_api_key
            if use_test_db
            else settings.qdrant_api_key
        )

        if not cluster_endpoint:
            env_var = "TEST_QDRANT_CLUSTER_ENDPOINT" if use_test_db else "QDRANT_CLUSTER_ENDPOINT"
            raise ValueError(f"{env_var} is not configured in the environment.")

        self.client = AsyncQdrantClient(url=cluster_endpoint, api_key=resolved_api_key, cloud_inference=True)# added cloud_inference=True to enable Qdrant Cloud Inference mode

    async def create_collection_if_not_exists(
        self,
        collection_name: str,
        vector_size: Optional[int] = None,
        distance: str = "Cosine",
    ) -> None:
        collections_response = await self.client.get_collections()
        existing_names = [c.name for c in collections_response.collections]

        if collection_name not in existing_names:
            distance_map = {
                "Cosine": models.Distance.COSINE,
                "Dot": models.Distance.DOT,
                "Euclid": models.Distance.EUCLID,
            }
            selected_distance = distance_map.get(distance, models.Distance.COSINE)

            # If vector_size is provided, configure vector index; otherwise create empty vector config
            vectors_config = (
                models.VectorParams(
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
        self, collection_name: str, points: List[VectorPoint]
    ) -> None:
        qdrant_points: List[models.PointStruct] = []

        for p in points:
            if p.vector is not None:
                point_vector = p.vector
            else:
                text_to_embed = p.payload.get("question") or p.payload.get("content") or ""
                point_vector = models.Document(
                    text=text_to_embed,
                    model=self.default_model,
                )

            qdrant_points.append(
                models.PointStruct(
                    id=p.id,
                    vector=point_vector,
                    payload=p.payload,
                )
            )

        await self.client.upsert(
            collection_name=collection_name,
            points=qdrant_points,
            wait=True,
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

        qdrant_points: List[models.PointStruct] = []

        for record in records:
            point_id = record.get(id_key)
            if not point_id:
                raise ValueError(
                    f"Record is missing required identifier key '{id_key}': {record}"
                )

            payload = {k: v for k, v in record.items() if k != id_key}

            qdrant_points.append(
                models.PointStruct(
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
        query_vector: Optional[List[float]] = None,
        query_text: Optional[str] = None,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        with_payload: bool = True,
    ) -> List[SearchResult]:
        if query_vector is not None:
            query_target = query_vector
        elif query_text is not None:
            query_target = models.Document(
                text=query_text,
                model=self.default_model,
            )
        else:
            raise ValueError("Either query_vector or query_text must be provided.")

        query_filter = None
        if filters:
            conditions = []
            for key, val in filters.items():
                if isinstance(val, list):
                    conditions.append(
                        models.FieldCondition(
                            key=key,
                            match=models.MatchAny(any=val),
                        )
                    )
                else:
                    conditions.append(
                        models.FieldCondition(
                            key=key,
                            match=models.MatchValue(value=val),
                        )
                    )
            query_filter = models.Filter(must=conditions)

        response = await self.client.query_points(
            collection_name=collection_name,
            query=query_target,
            query_filter=query_filter,
            limit=limit,
            with_payload=with_payload,
        )

        return [
            SearchResult(
                id=str(scored_point.id),
                score=scored_point.score,
                payload=scored_point.payload or {},
            )
            for scored_point in response.points
        ]

    async def close(self) -> None:
        await self.client.close()