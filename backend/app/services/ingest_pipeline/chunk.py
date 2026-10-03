import asyncio
from datetime import datetime, timezone
from typing import List
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from sqlalchemy import select, delete

from app.core.database import async_session
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.services.ingest_pipeline.clean_markdown import clean_markdown
from app.services.ingest_pipeline.orchestrator import is_substantive_chunk, estimate_token_count


async def process_and_chunk_pages(
    org_id: int,
    web_id: int,
    batch_size: int = 50,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> int:
    """
    Finds COMPLETED pages that have not been chunked yet (chunked_at is NULL).
    Cleans raw markdown, performs structural markdown header splitting,
    breaks into character chunks, and commits valid records to PostgreSQL.
    """
    async with async_session() as session:
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

        headers_to_split_on = [
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
            ("####", "Header 4"),
        ]
        header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on,
            strip_headers=False,
        )

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        total_chunks_created = 0

        for page in pages:
            raw_text = page.markdown_content or ""
            cleaned = clean_markdown(raw_text)

            if cleaned.startswith("---"):
                parts = cleaned.split("---", 2)
                if len(parts) >= 3:
                    cleaned = parts[2].strip()

            header_docs = header_splitter.split_text(cleaned)
            sections = header_docs if header_docs else [Document(page_content=cleaned)]
            valid_chunks: List[Chunk] = []

            for sec in sections:
                split_texts = text_splitter.split_text(sec.page_content)
                for text in split_texts:
                    stripped_chunk = text.strip()
                    if is_substantive_chunk(stripped_chunk):
                        valid_chunks.append(
                            Chunk(
                                page_id=page.id,
                                content=stripped_chunk,
                                token_count=estimate_token_count(stripped_chunk),
                                has_qgen=False,
                            )
                        )

            await session.execute(delete(Chunk).where(Chunk.page_id == page.id))

            if valid_chunks:
                session.add_all(valid_chunks)
                total_chunks_created += len(valid_chunks)

            page.chunked_at = datetime.now(timezone.utc)

        await session.commit()

    return total_chunks_created