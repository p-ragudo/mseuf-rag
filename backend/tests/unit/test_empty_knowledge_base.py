import asyncio

from app.models.org import Org
from app.routes import query as query_route
from app.services.query_pipeline.query_pipeline import QueryPipeline
from app.services.query_pipeline.schema import PipelineQueryRequest


class FakeDatabase:
    async def get(self, model, _org_id):
        assert model is Org
        return Org()


def test_query_readiness_reports_when_no_indexed_content_exists(monkeypatch):
    async def has_indexed_content(_org_id: int) -> bool:
        return False

    monkeypatch.setattr(
        QueryPipeline, "has_indexed_content", staticmethod(has_indexed_content)
    )

    readiness = asyncio.run(query_route.get_query_readiness(2, FakeDatabase()))

    assert readiness == {"has_indexed_content": False}


def test_empty_knowledge_base_returns_unavailable_without_running_retrieval(
    monkeypatch,
):
    pipeline = QueryPipeline.__new__(QueryPipeline)

    async def has_indexed_content(_org_id: int) -> bool:
        return False

    monkeypatch.setattr(pipeline, "has_indexed_content", has_indexed_content)

    result = asyncio.run(
        pipeline.execute(
            PipelineQueryRequest(org_id=1, query="What programs are available?")
        )
    )

    assert result.source == "fallback"
    assert result.answer == (
        "This organization hasn’t completed its knowledge-base setup yet. "
        "Please check back later or contact an organization administrator."
    )
