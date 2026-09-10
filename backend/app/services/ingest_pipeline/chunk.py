import asyncio
import re
from typing import List, Tuple
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.sql_db.base import DatabaseRepository
from app.services.sql_db.schema import DocumentChunk, ScrapedPageStatus


def clean_markdown_content(text: str) -> str:
    """Strips unnecessary HTML tags and excess markdown formatting noise."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_metadata_and_body(raw_markdown: str, fallback_url: str) -> Tuple[str, str]:
    """Extracts frontmatter if present, deriving title and content."""
    content = raw_markdown
    title = fallback_url.split("/")[-1].replace("-", " ").replace("_", " ").title() or "Untitled"

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].split("\n"):
                if line.startswith("title:"):
                    title = line.replace("title:", "").strip()
            content = parts[2]

    return title, clean_markdown_content(content)


async def process_and_chunk_pages(
    tenant_id: str,
    repo: DatabaseRepository,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> List[DocumentChunk]:
    """
    Fetches SCRAPED pages from the database, splits them into DocumentChunks,
    stores them into Postgres immediately per page, and marks each source page PROCESSED.
    """
    unprocessed_pages = await repo.list_pages_by_status(
        tenant_id=tenant_id,
        status=ScrapedPageStatus.SCRAPED,
    )

    if not unprocessed_pages:
        print(f"[{tenant_id}] No unprocessed scraped pages found.")
        return []

    print(f"[{tenant_id}] Processing {len(unprocessed_pages)} pages for chunking...")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    all_chunks: List[DocumentChunk] = []

    for page in unprocessed_pages:
        try:
            title, clean_content = extract_metadata_and_body(page.raw_markdown, page.source_url)
            if not clean_content:
                await repo.update_page_status(page.id, ScrapedPageStatus.FAILED)
                continue

            split_texts = text_splitter.split_text(clean_content)
            page_chunks: List[DocumentChunk] = []

            for idx, text_chunk in enumerate(split_texts):
                cleaned_text = text_chunk.strip()
                if len(cleaned_text) > 40:  # Skip trivial fragments
                    page_chunks.append(
                        DocumentChunk(
                            scraped_page_id=page.id,
                            tenant_id=tenant_id,
                            source_url=page.source_url,
                            title=title,
                            chunk_index=idx,
                            content=cleaned_text,
                        )
                    )

            if page_chunks:
                # Immediate atomic write to Postgres for this page's chunks
                await repo.delete_chunks_for_page(page.id)
                saved = await repo.save_chunks(page_chunks)
                all_chunks.extend(saved)
                await repo.update_page_status(page.id, ScrapedPageStatus.PROCESSED)
                print(f"[{tenant_id}] Checkpointed {len(saved)} chunks for: {page.source_url}")
            else:
                await repo.update_page_status(page.id, ScrapedPageStatus.FAILED)

        except Exception as e:
            print(f"[{tenant_id}] Error chunking page {page.source_url}: {e}")
            await repo.update_page_status(page.id, ScrapedPageStatus.FAILED)

    print(f"[{tenant_id}] Successfully persisted {len(all_chunks)} chunks (status=PENDING_QGEN).")
    return all_chunks


if __name__ == "__main__":
    from app.core.config import settings
    from app.services.sql_db.postgres_provider import PostgresDatabaseRepository

    async def standalone_chunk():
        repo = PostgresDatabaseRepository(dsn=settings.database_url)
        await repo.connect()
        try:
            await process_and_chunk_pages(tenant_id="mseuf", repo=repo)
        finally:
            await repo.close()

    asyncio.run(standalone_chunk())