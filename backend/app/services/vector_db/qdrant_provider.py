import asyncio
from typing import Any, Dict, List, Optional
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as rest_models
from app.core.config import settings

from .base import BaseVectorDB
from .schema import VectorPoint, SearchResult, SparseVectorData


class QdrantVectorDB(BaseVectorDB):
    def __init__(self, client: Optional[AsyncQdrantClient] = None):
        if client:
            self.client = client
            return

        is_dev = bool(settings.use_test_qdrant_db)

        if is_dev:
            cluster_endpoint = settings.test_qdrant_cluster_endpoint
            api_key = settings.test_qdrant_api_key
        else:
            cluster_endpoint = settings.qdrant_cluster_endpoint
            api_key = settings.qdrant_api_key

        if not cluster_endpoint:
            env_var = (
                "TEST_QDRANT_CLUSTER_ENDPOINT" if is_dev else "QDRANT_CLUSTER_ENDPOINT"
            )
            raise ValueError(f"{env_var} is not configured in the environment.")

        self.client = AsyncQdrantClient(url=cluster_endpoint, api_key=api_key)

    def _build_filter(self, filters: Optional[Dict[str, Any]]) -> Optional[rest_models.Filter]:
        if not filters:
            return None
        conditions = []
        for key, val in filters.items():
            if isinstance(val, list):
                conditions.append(
                    rest_models.FieldCondition(
                        key=key, match=rest_models.MatchAny(any=val)
                    )
                )
            else:
                conditions.append(
                    rest_models.FieldCondition(
                        key=key, match=rest_models.MatchValue(value=val)
                    )
                )
        return rest_models.Filter(must=conditions)

    async def create_collection_if_not_exists(
        self,
        collection_name: str,
        dense_vector_size: int,
        distance: str = "Cosine",
    ) -> None:
        """
        Creates a multi-tenant collection with named dense & sparse vectors,
        root HNSW m=0, and creates an isolated tenant index on `group_id`.
        """
        collections = await self.client.get_collections()
        existing_names = {col.name for col in collections.collections}

        if collection_name not in existing_names:
            distance_map = {
                "Cosine": rest_models.Distance.COSINE,
                "Dot": rest_models.Distance.DOT,
                "Euclid": rest_models.Distance.EUCLID,
            }
            selected_distance = distance_map.get(distance, rest_models.Distance.COSINE)

            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    "question_dense": rest_models.VectorParams(
                        size=dense_vector_size,
                        distance=selected_distance,
                        hnsw_config=rest_models.HnswConfigDiff(
                            m=0,  # Global graph disabled to prevent cross-tenant dead ends
                            payload_m=16,  # Multi-tenant sub-graph edges
                        ),
                    )
                },
                sparse_vectors_config={
                    "chunk_sparse": rest_models.SparseVectorParams(
                        index=rest_models.SparseIndexParams(on_disk=False)
                    )
                },
            )

            # Establish the tenant-aware index on group_id
            await self.client.create_payload_index(
                collection_name=collection_name,
                field_name="group_id",
                field_schema=rest_models.PayloadSchemaType.KEYWORD,
                is_tenant=True,
            )

    async def upsert_points(
        self, collection_name: str, points: List[VectorPoint]
    ) -> None:
        qdrant_points: List[rest_models.PointStruct] = []

        for p in points:
            converted_vectors: Dict[str, Any] = {}
            if isinstance(p.vector, dict):
                for v_name, v_val in p.vector.items():
                    if isinstance(v_val, SparseVectorData):
                        converted_vectors[v_name] = rest_models.SparseVector(
                            indices=v_val.indices,
                            values=v_val.values,
                        )
                    elif isinstance(v_val, dict) and "indices" in v_val:
                        converted_vectors[v_name] = rest_models.SparseVector(
                            indices=v_val["indices"],
                            values=v_val["values"],
                        )
                    else:
                        converted_vectors[v_name] = v_val
            else:
                converted_vectors = p.vector

            qdrant_points.append(
                rest_models.PointStruct(
                    id=p.id,
                    vector=converted_vectors,
                    payload=p.payload,
                )
            )

        await self.client.upsert(
            collection_name=collection_name, points=qdrant_points, wait=True
        )

    async def upsert_payload_only(
        self,
        collection_name: str,
        records: List[Dict[str, Any]],
        id_key: str = "id",
    ) -> None:
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
        query_vector: Optional[List[float]] = None,
        query_text: Optional[str] = None,
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        with_payload: bool = True,
        using_vector_name: str = "question_dense",
    ) -> List[SearchResult]:
        qdrant_filter = self._build_filter(filters)

        target_query = (
            rest_models.NamedVector(
                name=using_vector_name,
                vector=query_vector,
            )
            if query_vector is not None
            else None
        )

        response = await self.client.query_points(
            collection_name=collection_name,
            query=target_query,
            limit=limit,
            query_filter=qdrant_filter,
            with_payload=with_payload,
        )

        return [
            SearchResult(
                id=str(hit.id), score=hit.score, payload=hit.payload or {}
            )
            for hit in response.points
        ]

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
        qdrant_filter = self._build_filter(filters)

        target_query = rest_models.NamedSparseVector(
            name=using_vector_name,
            vector=rest_models.SparseVector(
                indices=sparse_indices,
                values=sparse_values,
            ),
        )

        response = await self.client.query_points(
            collection_name=collection_name,
            query=target_query,
            limit=limit,
            query_filter=qdrant_filter,
            with_payload=with_payload,
        )

        return [
            SearchResult(
                id=str(hit.id), score=hit.score, payload=hit.payload or {}
            )
            for hit in response.points
        ]

    async def close(self) -> None:
        if hasattr(self, "client") and self.client is not None:
            if hasattr(self.client, "close"):
                res = self.client.close()
                if asyncio.iscoroutine(res):
                    await res