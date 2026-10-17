import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from qdrant_client import AsyncQdrantClient

from app.core.database import Base
from app.core.config import settings

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

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
        # Patch application sessions to use test session
        monkeypatch.setattr("app.core.database.async_session", session_factory)
        monkeypatch.setattr("app.services.ingest_pipeline.chunk.async_session", session_factory)
        monkeypatch.setattr("app.services.ingest_pipeline.orchestrator.async_session", session_factory)
        monkeypatch.setattr("app.services.query_pipeline.query_pipeline.async_session", session_factory)
        monkeypatch.setattr("app.services.query_pipeline.context_expander.async_session", session_factory)
        yield session
        await session.rollback()

@pytest_asyncio.fixture
async def in_memory_qdrant() -> AsyncGenerator[AsyncQdrantClient, None]:
    client = AsyncQdrantClient(location=":memory:")
    yield client
    await client.close()