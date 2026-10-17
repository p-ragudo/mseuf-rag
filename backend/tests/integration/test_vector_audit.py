import pytest
from unittest.mock import AsyncMock, patch
from qdrant_client.http import models as rest_models

from app.services.vector_db.qdrant_provider import QdrantVectorDB
from app.services.vector_db.schema import VectorPoint, SparseVectorData
from app.core.config import settings

@pytest.mark.asyncio
async def test_collection_vector_audit_and_quantization_schema(in_memory_qdrant):
    qdrant_db = QdrantVectorDB(client=in_memory_qdrant)
    collection_name = "test_vector_audit"
    dense_dim = 768

    created_indexes = []
    original_create_payload_index = in_memory_qdrant.create_payload_index

    async def track_payload_index(collection_name, field_name, field_schema=None, **kwargs):
        created_indexes.append((field_name, field_schema))
        return await original_create_payload_index(collection_name, field_name, field_schema=field_schema, **kwargs)

    with patch.object(in_memory_qdrant, "create_payload_index", side_effect=track_payload_index), \
         patch.object(settings, "quantization_enabled", True), \
         patch.object(settings, "quantization_type", "scalar"), \
         patch.object(settings, "quantization_always_ram", True):
        
        await qdrant_db.create_collection_if_not_exists(
            collection_name=collection_name,
            dense_vector_size=dense_dim,
            distance="Cosine",
            enable_quantization=True,
        )

    col_info = await in_memory_qdrant.get_collection(collection_name)
    dense_cfg = col_info.config.params.vectors["question_dense"]
    sparse_cfg = col_info.config.params.sparse_vectors["chunk_sparse"]

    # 1. Verify Vector Schema & HNSW Topology
    assert dense_cfg.size == dense_dim
    assert dense_cfg.distance == rest_models.Distance.COSINE
    assert dense_cfg.hnsw_config.m == 0
    assert dense_cfg.hnsw_config.payload_m == 16
    assert sparse_cfg.modifier == rest_models.Modifier.IDF

    # 2. Verify Quantization Configuration
    q_cfg = dense_cfg.quantization_config.scalar
    assert q_cfg.type == rest_models.ScalarType.INT8
    assert q_cfg.quantile == 0.99
    assert q_cfg.always_ram is True

    # 3. Verify Payload Indexes created by provider
    indexed_fields = {name for name, _ in created_indexes}
    assert "group_id" in indexed_fields
    assert "campus" in indexed_fields
    assert "page_id" in indexed_fields
    assert "chunk_id" in indexed_fields

    group_id_schema = next(schema for name, schema in created_indexes if name == "group_id")
    assert group_id_schema.is_tenant is True

@pytest.mark.asyncio
async def test_vector_point_payload_strictness(in_memory_qdrant):
    qdrant_db = QdrantVectorDB(client=in_memory_qdrant)
    collection_name = "test_payload_audit"
    await qdrant_db.create_collection_if_not_exists(collection_name, dense_vector_size=768)

    sample_point = VectorPoint(
        id="a3bb189e-8bf9-4888-9912-ace4e6543000",
        vector={
            "question_dense": [0.05] * 768,
            "chunk_sparse": SparseVectorData(indices=[1, 42, 105], values=[0.3, 1.2, 0.8]),
        },
        payload={
            "group_id": "1",
            "web_id": 10,
            "parent_chunk_id": "b3bb189e-8bf9-4888-9912-ace4e6543001",
            "question_text": "What is the tuition fee?",
            "chunk_text": "Tuition fees for AY 2026-2027 are 30,000 PHP.",
            "source_url": "https://university.edu/tuition",
            "page_id": 100,
            "chunk_id": 200,
            "chunk_index": 0,
            "section_id": "sec_001",
            "heading_path": "Admissions > Fees",
            "doc_type": "evergreen",
            "campus": "main",
            "academic_level": "undergraduate",
            "doc_period": 2026,
            "page_updated_at": "2026-10-15T00:00:00",
        },
    )

    await qdrant_db.upsert_points(collection_name, [sample_point])

    res = await qdrant_db.search(
        collection_name=collection_name,
        query_vector=[0.05] * 768,
        filters={"group_id": "1"},
        limit=1,
    )
    assert len(res) == 1
    p = res[0].payload
    assert p["group_id"] == "1"
    assert p["doc_period"] == 2026
    assert p["academic_level"] == "undergraduate"
    assert p["campus"] == "main"

@pytest.mark.asyncio
async def test_search_quantization_rescore_parameters(in_memory_qdrant):
    qdrant_db = QdrantVectorDB(client=in_memory_qdrant)
    collection_name = "test_rescore"
    await qdrant_db.create_collection_if_not_exists(collection_name, dense_vector_size=4)

    with patch.object(in_memory_qdrant, "query_points", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = rest_models.QueryResponse(points=[])
        with patch.object(settings, "quantization_enabled", True), \
             patch.object(settings, "quantization_rescore", True), \
             patch.object(settings, "quantization_oversampling", 2.0):

            await qdrant_db.search(
                collection_name=collection_name,
                query_vector=[0.1, 0.2, 0.3, 0.4],
                limit=5,
            )

            assert mock_query.called
            call_kwargs = mock_query.call_args.kwargs
            search_params = call_kwargs["search_params"]
            assert search_params.quantization.rescore is True
            assert search_params.quantization.oversampling == 2.0