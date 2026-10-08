from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, func, select

from app.core.database import async_session
from app.models.chunk import Chunk
from app.models.scraped_page import PageProcessStatus, ScrapedPage
from app.services.ingest_pipeline.chunker import chunk_markdown, estimate_token_count
from app.services.ingest_pipeline.clean_markdown import clean_markdown
from app.utils.temporal import extract_doc_period


def _page_title_from_url(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    if not slug or slug.startswith(("http", "www")):
        return "Homepage"
    return slug.replace("-", " ").replace("_", " ").strip().title() or "Homepage"


async def process_and_chunk_pages(
    web_id: int,
    org_id: Optional[int] = None,
    batch_size: int = 20,
) -> int:
    """
    Takes COMPLETED pages with chunked_at IS NULL, cleans them, chunks them,
    replaces the page's old chunks and stamps chunked_at.

    NEW: when a page already had chunks, its old Qdrant points are now orphans
    (new chunk rows get new ids), so the page is flagged `qdrant_cleanup_pending`
    and swept by the orchestrator once the new points are synced.
    Also records the page-level academic period.
    """
    async with async_session() as session:
        conditions = [
            ScrapedPage.web_id == web_id,
            ScrapedPage.status == PageProcessStatus.COMPLETED,
            ScrapedPage.chunked_at.is_(None),
            ScrapedPage.markdown_content.is_not(None),
        ]
        if org_id is not None:
            conditions.append(ScrapedPage.org_id == org_id)

        res = await session.execute(select(ScrapedPage).where(*conditions).limit(batch_size))
        pages = list(res.scalars().all())
        if not pages:
            return 0

        total_created = 0
        for page in pages:
            cleaned = clean_markdown(page.markdown_content or "")
            drafts = chunk_markdown(cleaned, page_title=_page_title_from_url(page.url))

            had_old_chunks = (
                await session.scalar(
                    select(func.count(Chunk.id)).where(Chunk.page_id == page.id)
                )
                or 0
            ) > 0
            await session.execute(delete(Chunk).where(Chunk.page_id == page.id))

            new_chunks: List[Chunk] = [
                Chunk(
                    page_id=page.id,
                    content=d.content,
                    token_count=estimate_token_count(d.content),
                    has_qgen=False,
                    chunk_index=d.chunk_index,
                    section_id=d.section_id,
                    heading_path=d.heading_path or None,
                    part_index=d.part_index,
                    part_total=d.part_total,
                )
                for d in drafts
            ]
            if new_chunks:
                session.add_all(new_chunks)
                total_created += len(new_chunks)

            page.doc_period = extract_doc_period(cleaned, url=page.url)
            if had_old_chunks:
                page.qdrant_cleanup_pending = True
            page.chunked_at = datetime.now(timezone.utc)

        await session.commit()
    return total_created