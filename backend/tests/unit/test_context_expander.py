import pytest
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.services.query_pipeline.context_expander import ContextExpander
from app.services.reranker.schema import RerankResult

@pytest.mark.asyncio
async def test_context_expander_stitches_consecutive_parts(db_session):
    page = ScrapedPage(org_id=1, web_id=1, url="https://uni.edu/procedure", status=PageProcessStatus.COMPLETED)
    db_session.add(page)
    await db_session.flush()

    chunks = [
        Chunk(page_id=page.id, chunk_index=0, section_id="sec_1", content="Step 1: Fill out the online form.", token_count=10),
        Chunk(page_id=page.id, chunk_index=1, section_id="sec_1", content="Step 2: Pay the application fee.", token_count=10),
        Chunk(page_id=page.id, chunk_index=2, section_id="sec_1", content="Step 3: Upload supporting credentials.", token_count=10),
    ]
    db_session.add_all(chunks)
    await db_session.commit()

    # Hit references only Chunk #2 (Step 2)
    rerank_result = RerankResult(
        chunk_id=str(chunks[1].id),
        content="Step 2: Pay the application fee.",
        initial_score=0.9,
        rerank_score=0.88,
        payload={"chunk_id": chunks[1].id, "campus": "main"},
    )

    expander = ContextExpander(window=1, expand_top_n=1, max_chars=1000)
    expanded_contexts = await expander.expand(org_id=1, results=[rerank_result])

    assert len(expanded_contexts) == 1
    # Full contiguous reading order must be unified
    stitched_text = expanded_contexts[0].content
    assert "Step 1: Fill out the online form." in stitched_text
    assert "Step 2: Pay the application fee." in stitched_text
    assert "Step 3: Upload supporting credentials." in stitched_text

@pytest.mark.asyncio
async def test_context_expander_enforces_tenant_boundary(db_session):
    # Page belonging to Org 2
    foreign_page = ScrapedPage(org_id=2, web_id=99, url="https://leak.com/doc", status=PageProcessStatus.COMPLETED)
    db_session.add(foreign_page)
    await db_session.flush()

    foreign_chunk = Chunk(page_id=foreign_page.id, chunk_index=0, content="Private Org 2 Data", token_count=5)
    db_session.add(foreign_chunk)
    await db_session.commit()

    # Query executing under Org 1 attempting to expand Org 2 chunk
    hit = RerankResult(
        chunk_id=str(foreign_chunk.id),
        content="Private Org 2 Data",
        initial_score=0.9,
        rerank_score=0.88,
        payload={"chunk_id": foreign_chunk.id, "campus": "main"},
    )

    expander = ContextExpander()
    # ScrapedPage.org_id == 1 check in ContextExpander marks this as an orphaned hit
    expanded = await expander.expand(org_id=1, results=[hit])
    # Orphaned chunks from mismatched tenants are completely dropped
    assert len(expanded) == 0