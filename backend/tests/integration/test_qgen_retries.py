import pytest
import asyncio
from unittest.mock import AsyncMock
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.services.ingest_pipeline.orchestrator import qgen_worker, QGEN_MAX_ATTEMPTS

@pytest.mark.asyncio
async def test_qgen_worker_increments_attempts_on_failure(db_session, monkeypatch):
    # Use isolated web_id=505
    isolated_web_id = 505
    page = ScrapedPage(
        org_id=1,
        web_id=isolated_web_id,
        url="https://uni.edu/qgen-test",
        status=PageProcessStatus.COMPLETED,
    )
    db_session.add(page)
    await db_session.flush()

    chunk = Chunk(
        page_id=page.id,
        content="Substantive chunk content about university admission guidelines.",
        token_count=10,
        has_qgen=False,
        qgen_attempts=0,
    )
    db_session.add(chunk)
    await db_session.commit()

    # Mock generator consistently raising an exception to test retry limits
    mock_generator = AsyncMock()
    mock_generator.generate_questions_batch.side_effect = ValueError("Corrupt JSON from LLM")
    monkeypatch.setattr(
        "app.services.ingest_pipeline.orchestrator.get_question_generator",
        lambda: mock_generator,
    )

    is_chunking_done = asyncio.Event()
    is_chunking_done.set()

    # Run qgen worker to exhaustion
    await qgen_worker(web_id=isolated_web_id, is_chunking_done=is_chunking_done)

    await db_session.refresh(chunk)
    # The chunk must NOT be marked as successful
    assert chunk.has_qgen is False
    # The worker must retry up to QGEN_MAX_ATTEMPTS (3) and then gracefully exit the loop
    assert chunk.qgen_attempts == QGEN_MAX_ATTEMPTS