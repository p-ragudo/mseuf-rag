import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.embeddings.schema import EmbeddingResult
from app.services.ingest_pipeline import orchestrator
from app.services.vector_db.schema import SparseVectorData


class FakeResult:
    def __init__(self, rows=()):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, state):
        self.state = state

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _statement):
        if not self.state["returned_rows"]:
            self.state["returned_rows"] = True
            return FakeResult([self.state["row"]])
        return FakeResult()

    async def scalar(self, _statement):
        return 0

    async def commit(self):
        return None

    async def rollback(self):
        return None


class FakeVectorDB:
    def __init__(self):
        self.points = []

    async def create_collection_if_not_exists(self, **_kwargs):
        return None

    async def upsert_points(self, collection_name, points):
        self.collection_name = collection_name
        self.points.extend(points)


class FakeEmbedder:
    dimension = 2

    async def embed(self, texts, task_type):
        assert texts == ["Which documents are needed for admission?"]
        assert task_type == "RETRIEVAL_DOCUMENT"
        return [EmbeddingResult(values=[0.25, 0.75])]


class FakeSparseEmbedder:
    async def embed_text(self, text):
        assert text == "Applicants must submit the application form and transcript."
        return SparseVectorData(indices=[4, 8], values=[0.5, 0.7])


def test_document_sync_upserts_tenant_scoped_points(monkeypatch):
    row = SimpleNamespace(
        q_id=42,
        q_text="Which documents are needed for admission?",
        chunk_id=12,
        chunk_content="Applicants must submit the application form and transcript.",
        chunk_index=0,
        section_id="admissions",
        heading_path="Admissions",
        part_index=0,
        part_total=1,
        page_id=3,
        page_url="document://document-id/admissions.pdf",
        page_doc_period=None,
        page_updated_at=datetime.now(timezone.utc),
    )
    state = {"returned_rows": False, "row": row}
    vector_db = FakeVectorDB()
    monkeypatch.setattr(orchestrator, "async_session", lambda: FakeSession(state))
    monkeypatch.setattr(orchestrator, "get_vector_db", lambda: vector_db)
    monkeypatch.setattr(orchestrator, "get_embedder", FakeEmbedder)
    monkeypatch.setattr(orchestrator, "get_sparse_embedder", FakeSparseEmbedder)
    monkeypatch.setattr(
        orchestrator,
        "get_active_sync_column",
        lambda: SimpleNamespace(key="is_synced_qdrant", is_=lambda _value: True),
    )
    monkeypatch.setattr(
        orchestrator,
        "settings",
        SimpleNamespace(resolved_collection_name="test-collection", quantization_enabled=False),
    )

    qgen_done = asyncio.Event()
    qgen_done.set()
    synced = asyncio.run(
        orchestrator.qdrant_sync_worker(
            org_id=17,
            web_id=29,
            is_qgen_done=qgen_done,
        )
    )

    assert synced == 1
    assert vector_db.collection_name == "test-collection"
    assert len(vector_db.points) == 1
    point = vector_db.points[0]
    assert point.payload["group_id"] == "17"
    assert point.payload["web_id"] == 29
    assert point.vector["question_dense"] == [0.25, 0.75]
    assert point.vector["chunk_sparse"] == SparseVectorData(
        indices=[4, 8], values=[0.5, 0.7]
    )
