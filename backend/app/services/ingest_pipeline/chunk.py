from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, select

from app.core.database import async_session
from app.models.chunk import Chunk
from app.models.scraped_page import PageProcessStatus, ScrapedPage
from app.services.ingest_pipeline.chunker import chunk_markdown, estimate_token_count
from app.services.ingest_pipeline.clean_markdown import clean_markdown


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
    Single implementation used by BOTH the orchestrator's chunker_worker and
    any standalone script (the two used to be duplicated copies).

    Takes COMPLETED pages with chunked_at IS NULL, cleans them, chunks them
    with the structure-aware chunker, replaces the page's old chunks and
    stamps chunked_at. Returns the number of chunks created (0 when there
    is no pending page).
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

            page.chunked_at = datetime.now(timezone.utc)

        await session.commit()
    return total_created
