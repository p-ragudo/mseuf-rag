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

    def _build_filter(
        self,
        filters: Optional[Dict[str, Any]],
        must_not: Optional[Dict[str, Any]] = None,
    ) -> Optional[rest_models.Filter]:
        if not filters and not must_not:
            return None

        def _conds(d: Optional[Dict[str, Any]]) -> List[rest_models.FieldCondition]:
            out: List[rest_models.FieldCondition] = []
            for key, val in (d or {}).items():
                if isinstance(val, list):
                    out.append(rest_models.FieldCondition(key=key, match=rest_models.MatchAny(any=val)))
                else:
                    out.append(rest_models.FieldCondition(key=key, match=rest_models.MatchValue(value=val)))
            return out

        return rest_models.Filter(
            must=_conds(filters) or None,
            must_not=_conds(must_not) or None,
        )

    def _get_quantization_config(self) -> Optional[rest_models.QuantizationConfig]:
        if not settings.quantization_enabled:
            return None

        q_type = settings.quantization_type.lower()
        if q_type == "binary":
            return rest_models.BinaryQuantization(
                binary=rest_models.BinaryQuantizationConfig(
                    always_ram=settings.quantization_always_ram,
                )
            )
        else:
            return rest_models.ScalarQuantization(
                scalar=rest_models.ScalarQuantizationConfig(
                    type=rest_models.ScalarType.INT8,
                    quantile=0.99,
                    always_ram=settings.quantization_always_ram,
                )
            )

    async def create_collection_if_not_exists(
        self,
        collection_name: str,
        dense_vector_size: Optional[int] = None,
        distance: str = "Cosine",
        enable_quantization: Optional[bool] = None,
    ) -> None:
        collections = await self.client.get_collections()
        existing_names = {col.name for col in collections.collections}

        use_quantization = (
            enable_quantization
            if enable_quantization is not None
            else settings.quantization_enabled
        )

        quantization_cfg = (
            self._get_quantization_config() if use_quantization else None
        )

        if collection_name not in existing_names:
            if dense_vector_size is None:
                raise ValueError("dense_vector_size is required to create a new collection.")

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
                        on_disk=True,
                        hnsw_config=rest_models.HnswConfigDiff(
                            m=0,
                            payload_m=16,
                        ),
                        quantization_config=quantization_cfg,
                    )
                },
                sparse_vectors_config={
                    "chunk_sparse": rest_models.SparseVectorParams(
                        index=rest_models.SparseIndexParams(on_disk=False),
                        modifier=rest_models.Modifier.IDF,
                    )
                },
            )
        else:
            collection_info = await self.client.get_collection(collection_name)
            existing_params = collection_info.config.params.vectors
            target_params = None
            if isinstance(existing_params, dict):
                target_params = existing_params.get("question_dense")
            
            if use_quantization and target_params and not target_params.quantization_config:
                await self.client.update_collection(
                    collection_name=collection_name,
                    quantization_config=quantization_cfg,
                )

        collection_info = await self.client.get_collection(collection_name)
        payload_schema = collection_info.payload_schema or {}

        if "group_id" not in payload_schema:
            await self.client.create_payload_index(
                collection_name=collection_name,
                field_name="group_id",
                field_schema=rest_models.KeywordIndexParams(
                    type="keyword",
                    is_tenant=True,
                ),
            )

        if "campus" not in payload_schema:
            await self.client.create_payload_index(
                collection_name=collection_name,
                field_name="campus",
                field_schema=rest_models.KeywordIndexParams(
                    type="keyword",
                ),
            )

        if "page_id" not in payload_schema:
            await self.client.create_payload_index(
                collection_name=collection_name,
                field_name="page_id",
                field_schema=rest_models.PayloadSchemaType.INTEGER,
            )

        if "chunk_id" not in payload_schema:
            await self.client.create_payload_index(
                collection_name=collection_name,
                field_name="chunk_id",
                field_schema=rest_models.PayloadSchemaType.INTEGER,
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
        rescore: Optional[bool] = None,
        oversampling: Optional[float] = None,
    ) -> List[SearchResult]:
        qdrant_filter = self._build_filter(filters)

        search_params = None
        if settings.quantization_enabled:
            search_params = rest_models.SearchParams(
                quantization=rest_models.QuantizationSearchParams(
                    rescore=(
                        rescore
                        if rescore is not None
                        else settings.quantization_rescore
                    ),
                    oversampling=(
                        oversampling
                        if oversampling is not None
                        else settings.quantization_oversampling
                    ),
                )
            )

        response = await self.client.query_points(
            collection_name=collection_name,
            query=query_vector,
            using=using_vector_name,
            limit=limit,
            query_filter=qdrant_filter,
            search_params=search_params,
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

        sparse_query = rest_models.SparseVector(
            indices=sparse_indices,
            values=sparse_values,
        )

        response = await self.client.query_points(
            collection_name=collection_name,
            query=sparse_query,
            using=using_vector_name,
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

    async def delete_points(
        self,
        collection_name: str,
        filters: Dict[str, Any],
        must_not: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not filters or "group_id" not in filters:
            raise ValueError("delete_points requires a group_id (tenant) filter.")
        await self.client.delete(
            collection_name=collection_name,
            points_selector=rest_models.FilterSelector(
                filter=self._build_filter(filters, must_not)
            ),
            wait=True,
        )

    async def delete_points_by_ids(
        self,
        collection_name: str,
        point_ids: List[str],
    ) -> None:
        if not point_ids:
            return
        BATCH_SIZE = 500
        for i in range(0, len(point_ids), BATCH_SIZE):
            batch = point_ids[i : i + BATCH_SIZE]
            await self.client.delete(
                collection_name=collection_name,
                points_selector=rest_models.PointIdsList(points=batch),
                wait=True,
            )

    async def close(self) -> None:
        if hasattr(self, "client") and self.client is not None:
            if hasattr(self.client, "close"):
                res = self.client.close()
                if asyncio.iscoroutine(res):
                    await res