import asyncio
from datetime import datetime, timezone
from typing import List
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select, delete

from app.core.database import async_session_factory
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.services.cleaner import clean_markdown


def estimate_token_count(text: str) -> int:
    """Estimates tokens using whitespace heuristics (or 4 chars/token fallback)."""
    return max(1, len(text.split()))


async def process_and_chunk_pages(
    org_id: int,
    web_id: int,
    batch_size: int = 50,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> int:
    """
    Finds COMPLETED pages that have not been chunked yet (chunked_at is NULL).
    Cleans raw markdown in-memory, splits into chunks, saves to the chunks table,
    and timestamps chunked_at on the source page.
    """
    async with async_session_factory() as session:
        stmt = (
            select(ScrapedPage)
            .where(
                ScrapedPage.org_id == org_id,
                ScrapedPage.web_id == web_id,
                ScrapedPage.status == PageProcessStatus.COMPLETED,
                ScrapedPage.chunked_at.is_(None),
                ScrapedPage.markdown_content.is_not(None),
            )
            .limit(batch_size)
        )
        res = await session.execute(stmt)
        pages = list(res.scalars().all())

        if not pages:
            return 0

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        total_chunks_created = 0

        for page in pages:
            raw_text = page.markdown_content or ""
            cleaned = clean_markdown(raw_text)

            # Strip optional frontmatter if present
            if cleaned.startswith("---"):
                parts = cleaned.split("---", 2)
                if len(parts) >= 3:
                    cleaned = parts[2].strip()

            split_texts = text_splitter.split_text(cleaned)
            valid_chunks: List[Chunk] = []

            for text in split_texts:
                stripped_chunk = text.strip()
                if len(stripped_chunk) > 40:  # Skip trivial fragments
                    valid_chunks.append(
                        Chunk(
                            page_id=page.id,
                            content=stripped_chunk,
                            token_count=estimate_token_count(stripped_chunk),
                            has_qgen=False,
                        )
                    )

            # Clear old chunks for idempotency if re-running
            await session.execute(delete(Chunk).where(Chunk.page_id == page.id))

            if valid_chunks:
                session.add_all(valid_chunks)
                total_chunks_created += len(valid_chunks)

            # Mark page as chunked
            page.chunked_at = datetime.now(timezone.utc)

        await session.commit()

    return total_chunks_created