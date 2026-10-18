import asyncio
import hashlib
import json
import math
from typing import AsyncGenerator, List, Optional
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import ARRAY
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as rest_models

from app.main import app
from app.core.config import settings
from app.core.database import Base
from app.services.embeddings.base import BaseEmbedder
from app.services.embeddings.schema import EmbedderConfig, EmbeddingResult
from app.services.vector_db.qdrant_provider import QdrantVectorDB

TEST_COLLECTION_NAME = "test_ephemeral_benchmarks_s768"
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

# ---------------------------------------------------------------------------
# Zero-Risk Dialect Patch for Tests:
# Teaches PostgreSQL ARRAY how to compile DDL and bind lists under SQLite.
# This leaves production PostgreSQL behavior 100% untouched.
# ---------------------------------------------------------------------------
@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    return "JSON"

_orig_bind_processor = ARRAY.bind_processor
def _sqlite_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        return lambda val: json.dumps(val) if val is not None else None
    return _orig_bind_processor(self, dialect)
ARRAY.bind_processor = _sqlite_bind_processor

_orig_result_processor = ARRAY.result_processor
def _sqlite_result_processor(self, dialect, coltype):
    if dialect.name == "sqlite":
        return lambda val: json.loads(val) if isinstance(val, str) else (val or [])
    return _orig_result_processor(self, dialect, coltype)
ARRAY.result_processor = _sqlite_result_processor


class Deterministic768Embedder(BaseEmbedder):
    """
    Generates deterministic, unit-normalized 768-dim vectors from text.
    Allows exact mathematical similarity tests on Qdrant and Redis
    without consuming Gemini API quotas or triggering 429 rate limits.
    """
    def __init__(self, config: Optional[EmbedderConfig] = None) -> None:
        cfg = config or EmbedderConfig(
            provider="deterministic",
            model_name="deterministic-768",
            api_key="mock",
            output_dimensionality=768,
        )
        super().__init__(cfg)
        self._dim = 768

    async def embed(
        self, texts: List[str], task_type: Optional[str] = None
    ) -> List[EmbeddingResult]:
        results = []
        for text in texts:
            h = hashlib.sha256(text.encode("utf-8")).digest()
            raw_vals = [(float(b) / 255.0) - 0.5 for b in h]
            tiled = (raw_vals * (self._dim // len(raw_vals) + 1))[: self._dim]
            norm = math.sqrt(sum(x * x for x in tiled)) or 1.0
            results.append(EmbeddingResult(values=[x / norm for x in tiled]))
        return results

    @property
    def dimension(self) -> int:
        return self._dim


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine, monkeypatch) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        monkeypatch.setattr("app.core.database.async_session", session_factory)
        monkeypatch.setattr("app.services.ingest_pipeline.chunk.async_session", session_factory)
        monkeypatch.setattr("app.services.ingest_pipeline.orchestrator.async_session", session_factory)
        monkeypatch.setattr("app.services.query_pipeline.query_pipeline.async_session", session_factory)
        monkeypatch.setattr("app.services.query_pipeline.context_expander.async_session", session_factory)
        monkeypatch.setattr("app.routes.auth.get_db", lambda: session)
        monkeypatch.setattr("app.routes.orgs.get_db", lambda: session)
        monkeypatch.setattr("app.routes.websites.get_db", lambda: session)
        monkeypatch.setattr("app.routes.ingest.get_db", lambda: session)
        monkeypatch.setattr("app.routes.query.get_db", lambda: session)
        monkeypatch.setattr("app.routes.stats.get_db", lambda: session)
        monkeypatch.setattr("app.routes.branding.get_db", lambda: session)
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def live_or_mock_qdrant(monkeypatch) -> AsyncGenerator[QdrantVectorDB, None]:
    endpoint = settings.active_qdrant_endpoint
    api_key = settings.active_qdrant_api_key

    client = None
    if endpoint and "qdrant" in endpoint:
        try:
            client = AsyncQdrantClient(url=endpoint, api_key=api_key, timeout=10.0)
            await client.get_collections()
        except Exception:
            client = None

    if client is None:
        client = AsyncQdrantClient(location=":memory:")

    qdrant_db = QdrantVectorDB(client=client)

    # Prevent endpoints from prematurely terminating the singleton client during tests
    original_close = client.close
    async def noop_close():
        pass
    client.close = noop_close

    monkeypatch.setattr(settings, "collection_name_use_prod", False)
    monkeypatch.setattr(settings, "collection_name_not_prod", TEST_COLLECTION_NAME)

    monkeypatch.setattr("app.services.vector_db.factory.get_vector_db", lambda: qdrant_db)
    monkeypatch.setattr("app.services.ingest_pipeline.orchestrator.get_vector_db", lambda: qdrant_db)
    monkeypatch.setattr("app.services.query_pipeline.query_pipeline.get_vector_db", lambda: qdrant_db)
    monkeypatch.setattr("app.routes.websites.get_vector_db", lambda: qdrant_db)

    # Initialize isolated test collection
    await qdrant_db.create_collection_if_not_exists(
        collection_name=TEST_COLLECTION_NAME,
        dense_vector_size=768,
        distance="Cosine",
        enable_quantization=True,
    )

    # Ensure integer index for web_id exists on cloud Qdrant
    try:
        await client.create_payload_index(
            collection_name=TEST_COLLECTION_NAME,
            field_name="web_id",
            field_schema=rest_models.PayloadSchemaType.INTEGER,
        )
    except Exception:
        pass

    yield qdrant_db

    try:
        await client.delete_collection(collection_name=TEST_COLLECTION_NAME)
    except Exception:
        pass
    try:
        client.close = original_close
        res = client.close()
        if asyncio.iscoroutine(res):
            await res
    except Exception:
        pass


@pytest_asyncio.fixture
async def in_memory_qdrant(live_or_mock_qdrant) -> AsyncQdrantClient:
    return live_or_mock_qdrant.client


@pytest_asyncio.fixture
async def api_client(db_session, live_or_mock_qdrant, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    embedder = Deterministic768Embedder()
    monkeypatch.setattr("app.services.embeddings.factory.get_embedder", lambda *args, **kwargs: embedder)
    monkeypatch.setattr("app.services.query_pipeline.query_pipeline.get_embedder", lambda *args, **kwargs: embedder)
    monkeypatch.setattr("app.services.ingest_pipeline.orchestrator.get_embedder", lambda *args, **kwargs: embedder)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client