import asyncio

from app.models.org import Org
from app.models.session_message import SessionMessage
from app.routes import query as query_route
from app.schemas.tenant import ChatTurn
from app.services.query_pipeline.schema import (
    PipelineQueryResponse,
    QueryBodyRequest,
)


class FakeDatabase:
    def __init__(self):
        self.added = []

    async def get(self, model, _org_id):
        assert model is Org
        return Org()

    def add(self, row):
        if not hasattr(row, "id"):
            row.id = 123
        self.added.append(row)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass


class FakePipeline:
    def __init__(self):
        self.request = None

    async def execute(self, request):
        self.request = request
        return PipelineQueryResponse(
            query=request.query,
            answer="Please continue without sharing sensitive information.",
            source="llm",
        )


def test_query_redacts_current_and_saved_history_before_pipeline(monkeypatch):
    async def load_history(_db, _org_id, _session_id):
        return [
            ChatTurn(role="user", content="Email me at old.address@example.com."),
        ]

    async def purge_expired(_db):
        pass

    monkeypatch.setattr(query_route, "load_history", load_history)
    monkeypatch.setattr(query_route, "purge_expired", purge_expired)

    db = FakeDatabase()
    pipeline = FakePipeline()
    response = asyncio.run(
        query_route.execute_query(
            org_id=1,
            body=QueryBodyRequest(
                query="Contact me at jane.doe@example.com.",
                session_id="test-session",
            ),
            db=db,
            pipeline=pipeline,
        )
    )

    assert pipeline.request.query == "Contact me at [REDACTED_EMAIL]."
    assert pipeline.request.history[0].content == (
        "Email me at [REDACTED_EMAIL]."
    )
    assert response.query == pipeline.request.query

    saved_user_turn = next(
        row
        for row in db.added
        if isinstance(row, SessionMessage) and row.role == "user"
    )
    assert saved_user_turn.content == pipeline.request.query
