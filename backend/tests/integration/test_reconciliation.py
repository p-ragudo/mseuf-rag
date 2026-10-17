import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from app.core.config import settings
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.services.ingest_pipeline.chunk import process_and_chunk_pages
from app.services.ingest_pipeline.orchestrator import (
    _apply_scrape_result,
    reconcile_stale_points,
    purge_missing_pages,
)

SUBSTANTIVE_MARKDOWN_V1 = """
# University Admission Procedures

Welcome prospective students. To begin your official admission process for AY 2026-2027:
1. Complete the initial registration form on our university portal.
2. Submit your certified high school transcript and certificate of good moral character.
3. Pay the official non-refundable processing fee of 500 PHP at the cashier.
4. Schedule your entrance examination with the testing center.
Please ensure all requirements are submitted before the announced deadline.
"""

SUBSTANTIVE_MARKDOWN_V2 = """
# University Admission Procedures

Welcome prospective students. To begin your official admission process for AY 2026-2027:
1. Complete the online admission form through the new student portal.
2. Upload scanned copies of your high school card and birth certificate.
3. Pay the processing fee online via partner digital payment channels.
4. Download your test permit immediately upon payment verification.
Please follow all instructions carefully to guarantee your exam slot.
"""

@pytest.mark.asyncio
async def test_content_hashing_and_change_detection(db_session):
    page = ScrapedPage(
        org_id=1,
        web_id=1,
        url="https://university.edu/admission",
        status=PageProcessStatus.PENDING,
    )
    raw_markdown = SUBSTANTIVE_MARKDOWN_V1 + "\nLast updated: 10:30 am."
    
    changed = _apply_scrape_result(page, raw_markdown)
    assert changed is True
    assert page.content_hash is not None
    assert page.status == PageProcessStatus.COMPLETED

    transient_markdown = SUBSTANTIVE_MARKDOWN_V1 + "\nLast updated: 11:45 pm."
    changed_again = _apply_scrape_result(page, transient_markdown)
    assert changed_again is False

    changed_third = _apply_scrape_result(page, SUBSTANTIVE_MARKDOWN_V2)
    assert changed_third is True

@pytest.mark.asyncio
async def test_rechunking_atomic_swap_and_cleanup_flag(db_session):
    # Unique web_id=101 to avoid cross-test contamination
    isolated_web_id = 101
    page = ScrapedPage(
        org_id=1,
        web_id=isolated_web_id,
        url="https://university.edu/steps",
        status=PageProcessStatus.COMPLETED,
        markdown_content=SUBSTANTIVE_MARKDOWN_V1,
    )
    db_session.add(page)
    await db_session.commit()
    await db_session.refresh(page)

    created_initial = await process_and_chunk_pages(web_id=isolated_web_id, org_id=1)
    assert created_initial > 0
    await db_session.refresh(page)
    assert page.qdrant_cleanup_pending is False

    page.markdown_content = SUBSTANTIVE_MARKDOWN_V2
    page.chunked_at = None
    await db_session.commit()

    created_updated = await process_and_chunk_pages(web_id=isolated_web_id, org_id=1)
    assert created_updated > 0
    await db_session.refresh(page)
    assert page.qdrant_cleanup_pending is True

@pytest.mark.asyncio
async def test_reconcile_stale_points_purges_dead_chunk_vectors(db_session, in_memory_qdrant, monkeypatch):
    from app.services.vector_db.qdrant_provider import QdrantVectorDB
    qdrant_db = QdrantVectorDB(client=in_memory_qdrant)
    monkeypatch.setattr("app.services.ingest_pipeline.orchestrator.get_vector_db", lambda: qdrant_db)

    collection_name = settings.resolved_collection_name
    await qdrant_db.create_collection_if_not_exists(collection_name, dense_vector_size=4)

    # Isolated web_id=999
    isolated_web_id = 999
    page = ScrapedPage(
        org_id=1,
        web_id=isolated_web_id,
        url="https://university.edu/page-to-clean-isolated",
        status=PageProcessStatus.COMPLETED,
        qdrant_cleanup_pending=True,
    )
    db_session.add(page)
    await db_session.flush()

    live_chunk = Chunk(
        page_id=page.id,
        content="Current chunk content",
        token_count=10,
        has_qgen=True,
    )
    db_session.add(live_chunk)
    await db_session.commit()

    deleted_filters = []
    async def mock_delete_points(collection_name, filters, must_not=None):
        deleted_filters.append({"filters": filters, "must_not": must_not})

    monkeypatch.setattr(qdrant_db, "delete_points", mock_delete_points)

    swept = await reconcile_stale_points(org_id=1, web_id=isolated_web_id)
    assert swept == 1
    assert len(deleted_filters) == 1
    assert deleted_filters[0]["filters"] == {"group_id": "1", "page_id": page.id}
    assert deleted_filters[0]["must_not"] == {"chunk_id": [live_chunk.id]}

    await db_session.refresh(page)
    assert page.qdrant_cleanup_pending is False

@pytest.mark.asyncio
async def test_purge_missing_pages_safety_guard(db_session, monkeypatch):
    run_started = datetime.now(timezone.utc)
    # Isolated web_id=888
    isolated_web_id = 888
    pages = [
        ScrapedPage(
            org_id=1,
            web_id=isolated_web_id,
            url=f"https://site.com/p{i}",
            status=PageProcessStatus.COMPLETED,
        )
        for i in range(4)
    ]
    db_session.add_all(pages)
    await db_session.commit()

    purged = await purge_missing_pages(
        org_id=1,
        web_id=isolated_web_id,
        run_started_at=run_started,
        discovered_count=1,
    )
    assert purged == 0

    count = (
        await db_session.execute(
            select(ScrapedPage).where(ScrapedPage.web_id == isolated_web_id)
        )
    ).scalars().all()
    assert len(count) == 4