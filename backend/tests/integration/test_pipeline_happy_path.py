import pytest
from unittest.mock import AsyncMock
from sqlalchemy import select

from app.models.website import Website, WebsiteScrapeStatus
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.models.generated_question import GeneratedQuestion
from app.services.ingest_pipeline.orchestrator import run_full_pipeline, get_active_sync_column
from app.services.llm_qgen.schema import GeneratedQuestion as LLMGenQuestion
from tests.conftest import TEST_COLLECTION_NAME


@pytest.mark.asyncio
async def test_full_ingestion_pipeline_happy_path(db_session, live_or_mock_qdrant, monkeypatch):
    # 1. Create a Website entry
    website = Website(id=701, org_id=99, url="https://happy-path.mseuf.edu.ph", status=WebsiteScrapeStatus.PENDING)
    db_session.add(website)
    await db_session.commit()

    # 2. Mock Discovery: discovers 1 substantive URL
    async def mock_discovery(*args, **kwargs):
        p = ScrapedPage(
            org_id=99,
            web_id=701,
            url="https://happy-path.mseuf.edu.ph/programs",
            status=PageProcessStatus.PENDING,
            markdown_content=None,
        )
        db_session.add(p)
        await db_session.commit()
        return 1

    monkeypatch.setattr("app.services.ingest_pipeline.orchestrator.run_discovery", mock_discovery)

    # 3. Mock Crawler with substantive structured markdown
    crawl_markdown = """
    # Computer Science Degree Offerings
    The Bachelor of Science in Computer Science is a 4-year degree program.
    Admission Requirements:
    1. Form 138 Senior High School report card with good standing.
    2. Passing score in the University Aptitude Entrance Examination.
    3. Certificate of Good Moral Character from previous principal.
    Tuition fee per semester is approximately 32,000 PHP.
    """
    mock_crawler = AsyncMock()
    mock_crawler.start = AsyncMock()
    mock_crawler.close = AsyncMock()
    mock_crawler.arun = AsyncMock(return_value=AsyncMock(success=True, markdown=crawl_markdown))
    monkeypatch.setattr("app.services.ingest_pipeline.orchestrator.AsyncWebCrawler", lambda *args, **kwargs: mock_crawler)

    # 4. Mock Question Generator
    mock_qgen = AsyncMock()
    async def mock_gen_batch(chunks):
        return {
            str(c.id): [
                LLMGenQuestion(id=f"q_{c.id}_1", chunk_id=str(c.id), content="What are the admission requirements for BSCS?", tags=["99"]),
                LLMGenQuestion(id=f"q_{c.id}_2", chunk_id=str(c.id), content="How much is the BSCS tuition fee?", tags=["99"]),
            ]
            for c in chunks
        }
    mock_qgen.generate_questions_batch = mock_gen_batch
    monkeypatch.setattr("app.services.ingest_pipeline.orchestrator.get_question_generator", lambda: mock_qgen)

    # 5. EXECUTE PIPELINE
    metrics = await run_full_pipeline(website_id=701, force_refresh=True)

    # 6. VERIFY METRICS
    assert metrics["scraped_pages"] == 1
    assert metrics["created_chunks"] >= 1
    assert metrics["generated_questions"] >= 2
    assert metrics["synced_qdrant_points"] >= 2

    # 7. VERIFY DATABASE COMPLETION CHECKPOINTS
    await db_session.refresh(website)
    assert website.status == WebsiteScrapeStatus.COMPLETED

    sync_col = get_active_sync_column()
    questions = (
        await db_session.execute(
            select(GeneratedQuestion)
            .join(Chunk, GeneratedQuestion.chunk_id == Chunk.id)
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(ScrapedPage.web_id == 701)
        )
    ).scalars().all()

    assert len(questions) >= 2
    for q in questions:
        assert getattr(q, sync_col.key) is True
        assert q.is_synced_qdrant is True

    # 8. VERIFY POINTS IN QDRANT
    points = await live_or_mock_qdrant.search(
        collection_name=TEST_COLLECTION_NAME,
        query_vector=[0.01] * 768,
        filters={"group_id": "99", "web_id": 701},
        limit=10,
    )
    assert len(points) >= 2
    assert "Computer Science Degree Offerings" in points[0].payload["chunk_text"]