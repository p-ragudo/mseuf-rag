import pytest
from unittest.mock import AsyncMock, patch
from app.services.query_pipeline.query_pipeline import QueryPipeline
from app.services.query_pipeline.schema import PipelineQueryRequest
from app.services.query_pipeline.intent_classifier import QueryIntent

@pytest.mark.asyncio
async def test_campus_zero_hits_falls_back_to_tenant_wide():
    pipeline = QueryPipeline()
    pipeline.embedder.embed_one = AsyncMock(return_value=AsyncMock(values=[0.1] * 768))
    pipeline.semantic_cache.get = AsyncMock(return_value=None)
    pipeline.sparse_embedder.embed_query = AsyncMock(return_value=AsyncMock(indices=[], values=[]))
    
    # Intent classifier detected a specific sub-campus
    pipeline.classifier.classify_intent = AsyncMock(
        return_value=QueryIntent(is_ambiguous=False, detected_sub_entity="candelaria")
    )

    searches_performed = []
    async def mock_hybrid_search(dense_vec, sparse_data, flt, limit):
        searches_performed.append(flt.copy())
        if "campus" in flt:
            return ([], [])  # First search with campus filter returns 0 hits
        # Second search without campus filter returns hit
        hit = AsyncMock(
            id="p1", score=0.8,
            payload={"parent_chunk_id": "c1", "chunk_text": "Main Campus Info", "question_text": "General Question"}
        )
        return ([hit], [])

    pipeline._hybrid_search = mock_hybrid_search
    pipeline.reranker.rerank = AsyncMock(return_value=[])

    req = PipelineQueryRequest(org_id=1, query="tuition fees")
    with patch.object(pipeline, "_resolve_org_details", AsyncMock(return_value=("Org", [], 0))):
        await pipeline.execute(req)

    # Must have attempted campus-specific first, then fallen back to tenant-wide
    assert len(searches_performed) == 2
    assert searches_performed[0] == {"group_id": "1", "campus": "candelaria"}
    assert searches_performed[1] == {"group_id": "1"}