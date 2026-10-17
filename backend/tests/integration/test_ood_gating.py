import pytest
from unittest.mock import AsyncMock, patch

from app.services.query_pipeline.query_pipeline import QueryPipeline
from app.services.query_pipeline.schema import PipelineQueryRequest
from app.services.reranker.schema import RerankCandidate, RerankResult
from app.services.query_pipeline.intent_classifier import QueryIntent
from app.services.llm_qa.schema import RetrievedContextItem
from app.core.config import settings

@pytest.fixture
def mock_pipeline():
    pipeline = QueryPipeline()
    pipeline.embedder.embed_one = AsyncMock(return_value=AsyncMock(values=[0.1] * 768))
    pipeline.semantic_cache.get = AsyncMock(return_value=None)
    pipeline.sparse_embedder.embed_query = AsyncMock(return_value=AsyncMock(indices=[], values=[]))
    pipeline.classifier.classify_intent = AsyncMock(
        return_value=QueryIntent(is_ambiguous=False, detected_sub_entity=None)
    )
    return pipeline

@pytest.mark.asyncio
async def test_empty_retrieval_returns_fallback_response(mock_pipeline):
    mock_pipeline._hybrid_search = AsyncMock(return_value=([], []))
    req = PipelineQueryRequest(org_id=1, query="How do I bake sourdough bread?")

    with patch.object(mock_pipeline, "_resolve_org_details", AsyncMock(return_value=("Test Org", [], 0))):
        res = await mock_pipeline.execute(req)

    assert res.source == "fallback"
    assert res.is_cached is False
    assert "No relevant institutional documents could be found" in res.answer
    assert len(res.contexts) == 0

@pytest.mark.asyncio
async def test_cross_encoder_threshold_rejection(mock_pipeline):
    mock_hit = AsyncMock(
        score=0.1,
        id="pt_1",
        payload={"parent_chunk_id": "chk_1", "chunk_text": "Random irrelevant text", "question_text": "q"}
    )
    mock_pipeline._hybrid_search = AsyncMock(return_value=([mock_hit], []))
    mock_pipeline.reranker.rerank = AsyncMock(return_value=[])

    req = PipelineQueryRequest(org_id=1, query="What is the capital of Mars?")

    with patch.object(mock_pipeline, "_resolve_org_details", AsyncMock(return_value=("Test Org", [], 0))):
        res = await mock_pipeline.execute(req)

    assert res.source == "fallback"
    assert "No sufficiently relevant institutional information was found" in res.answer
    assert mock_pipeline.reranker.rerank.called

@pytest.mark.asyncio
async def test_ambiguous_prompt_appends_clarification_note(mock_pipeline):
    mock_hit = AsyncMock(
        score=0.9,
        id="pt_1",
        payload={"parent_chunk_id": "chk_1", "chunk_text": "Enrollment is ongoing for all new students.", "question_text": "q"}
    )
    mock_pipeline._hybrid_search = AsyncMock(return_value=([mock_hit], []))
    
    mock_pipeline.reranker.rerank = AsyncMock(
        return_value=[
            RerankResult(
                chunk_id="chk_1",
                content="Enrollment is ongoing for all new students.",
                initial_score=0.9,
                rerank_score=0.85,
                payload={"chunk_id": 1, "source_url": "https://uni.edu/admissions"},
            )
        ]
    )

    # Return valid Pydantic models so QARequest validation succeeds
    valid_context = RetrievedContextItem(
        title="Admissions",
        content="Enrollment is ongoing for all new students starting August 2026.",
        source_url="https://uni.edu/admissions",
        campus="main",
        academic_level="undergraduate"
    )
    mock_pipeline.expander.expand = AsyncMock(return_value=[valid_context])
    mock_pipeline.qa_synthesizer.generate_answer = AsyncMock(
        return_value=AsyncMock(answer="Enrollment starts next week.", sources=["https://uni.edu/admissions"])
    )

    mock_pipeline.classifier.classify_intent = AsyncMock(
        return_value=QueryIntent(
            is_ambiguous=True,
            clarification_message="Are you inquiring about the Senior High School strand or Undergraduate programs?",
        )
    )

    req = PipelineQueryRequest(org_id=1, query="When is enrollment?")

    with patch.object(mock_pipeline, "_resolve_org_details", AsyncMock(return_value=("Test Org", [], 0))):
        res = await mock_pipeline.execute(req)

    assert res.source == "llm"
    assert "Enrollment starts next week." in res.answer
    assert "*Note*: Are you inquiring about the Senior High School strand" in res.answer