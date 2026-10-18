import pytest
from unittest.mock import AsyncMock, patch
from qdrant_client.http import models as rest_models

from app.services.vector_db.schema import VectorPoint, SparseVectorData
from app.core.config import settings
from tests.conftest import TEST_COLLECTION_NAME


@pytest.mark.asyncio
async def test_collection_vector_audit_and_quantization_schema(live_or_mock_qdrant):
    client = live_or_mock_qdrant.client
    dense_dim = 768

    col_info = await client.get_collection(TEST_COLLECTION_NAME)
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

    # 3. Verify Payload Indexes (if server mode supports payload_schema)
    if col_info.payload_schema:
        assert "group_id" in col_info.payload_schema
        assert col_info.payload_schema["group_id"].data_type == rest_models.PayloadSchemaType.KEYWORD


@pytest.mark.asyncio
async def test_vector_point_payload_strictness(live_or_mock_qdrant):
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

    await live_or_mock_qdrant.upsert_points(TEST_COLLECTION_NAME, [sample_point])

    res = await live_or_mock_qdrant.search(
        collection_name=TEST_COLLECTION_NAME,
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
async def test_search_quantization_rescore_parameters(live_or_mock_qdrant):
    client = live_or_mock_qdrant.client
    with patch.object(client, "query_points", new_callable=AsyncMock) as mock_query:
        mock_query.return_value = rest_models.QueryResponse(points=[])
        with patch.object(settings, "quantization_enabled", True), \
             patch.object(settings, "quantization_rescore", True), \
             patch.object(settings, "quantization_oversampling", 2.0):

            await live_or_mock_qdrant.search(
                collection_name=TEST_COLLECTION_NAME,
                query_vector=[0.1] * 768,
                limit=5,
            )

            assert mock_query.called
            call_kwargs = mock_query.call_args.kwargs
            search_params = call_kwargs["search_params"]
            assert search_params.quantization.rescore is True
            assert search_params.quantization.oversampling == 2.0