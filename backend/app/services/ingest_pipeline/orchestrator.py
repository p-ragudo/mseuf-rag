from datetime import datetime, timezone
from typing import List
from urllib.parse import urlparse

import tiktoken
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.database import async_session
from app.models.website import Website, WebsiteScrapeStatus
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.models.generated_question import GeneratedQuestion
from app.services.llm_qgen.factory import get_question_generator
from app.services.llm_qgen.schema import RawChunk

# Import discovery runner from the hardened discovery script
from app.services.ingest_pipeline.discovery import run_discovery

tokenizer = tiktoken.get_encoding("cl100k_base")


# =========================================================================
# Stage Helpers
# =========================================================================

def _simple_chunk_text(text: str, max_tokens: int = 500, overlap: int = 50) -> List[tuple[str, int]]:
    """Splits text by token length using tiktoken. Returns list of (chunk_text, token_count)."""
    tokens = tokenizer.encode(text)
    total_tokens = len(tokens)
    chunks = []
    start = 0

    while start < total_tokens:
        end = min(start + max_tokens, total_tokens)
        chunk_token_slice = tokens[start:end]
        chunk_str = tokenizer.decode(chunk_token_slice)
        chunks.append((chunk_str, len(chunk_token_slice)))

        if end == total_tokens:
            break
        start += max_tokens - overlap

    return chunks


# =========================================================================
# Pipeline Stages
# =========================================================================

async def scrape_pending_pages(web_id: int, max_retries: int = 3) -> int:
    """Fetches PENDING scraped_pages for this website and scrapes their markdown content."""
    scraped_count = 0
    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    async with async_session() as session:
        stmt = (
            select(ScrapedPage)
            .where(
                ScrapedPage.web_id == web_id,
                ScrapedPage.status == PageProcessStatus.PENDING,
                ScrapedPage.retries < max_retries,
            )
        )
        res = await session.execute(stmt)
        pending_pages = res.scalars().all()

        if not pending_pages:
            return 0

        async with AsyncWebCrawler() as crawler:
            for page in pending_pages:
                page.status = PageProcessStatus.IN_PROGRESS
                await session.commit()

                try:
                    crawl_result = await crawler.arun(url=page.url, config=config)
                    if crawl_result.success and crawl_result.markdown:
                        page.markdown_content = crawl_result.markdown
                        page.status = PageProcessStatus.COMPLETED
                        scraped_count += 1
                    else:
                        page.retries += 1
                        page.status = (
                            PageProcessStatus.FAILED
                            if page.retries >= max_retries
                            else PageProcessStatus.PENDING
                        )
                except Exception:
                    page.retries += 1
                    page.status = (
                        PageProcessStatus.FAILED
                        if page.retries >= max_retries
                        else PageProcessStatus.PENDING
                    )

                await session.commit()

    return scraped_count


async def chunk_completed_pages(web_id: int) -> int:
    """Processes COMPLETED scraped_pages that have not yet been chunked."""
    chunks_created = 0

    async with async_session() as session:
        stmt = select(ScrapedPage).where(
            ScrapedPage.web_id == web_id,
            ScrapedPage.status == PageProcessStatus.COMPLETED,
            ScrapedPage.chunked_at.is_(None),
            ScrapedPage.markdown_content.is_not(None),
        )
        res = await session.execute(stmt)
        pages = res.scalars().all()

        for page in pages:
            if not page.markdown_content or not page.markdown_content.strip():
                page.chunked_at = datetime.now(timezone.utc)
                await session.commit()
                continue

            raw_chunks = _simple_chunk_text(page.markdown_content)
            for chunk_content, token_count in raw_chunks:
                chunk = Chunk(
                    page_id=page.id,
                    content=chunk_content,
                    token_count=token_count,
                    has_qgen=False,
                )
                session.add(chunk)
                chunks_created += 1

            page.chunked_at = datetime.now(timezone.utc)
            await session.commit()

    return chunks_created


async def generate_questions_for_chunks(web_id: int) -> int:
    """Generates synthetic questions via LLM for chunks with has_qgen=False."""
    questions_created = 0
    generator = get_question_generator()

    async with async_session() as session:
        # Join Chunk with ScrapedPage to isolate by web_id
        stmt = (
            select(Chunk)
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(
                ScrapedPage.web_id == web_id,
                Chunk.has_qgen.is_(False),
            )
        )
        res = await session.execute(stmt)
        pending_chunks = res.scalars().all()

        for chunk in pending_chunks:
            # Build payload matching RawChunk schema
            raw_chunk_payload = RawChunk(
                chunk_id=chunk.id,
                content=chunk.content,
            )

            try:
                # LLM call returns List[GeneratedQuestionSchema]
                generated = await generator.generate_questions(raw_chunk_payload)

                for item in generated:
                    # Model expects chunk_id, question text, and sync status
                    q_record = GeneratedQuestion(
                        chunk_id=chunk.id,
                        question=item.question if hasattr(item, "question") else str(item),
                        is_synced_qdrant=False,
                    )
                    session.add(q_record)
                    questions_created += 1

                chunk.has_qgen = True
                await session.commit()

            except Exception as e:
                # Skip chunk mutation so it can be retried without breaking the job
                await session.rollback()
                print(f"[QGen Error] Failed chunk_id={chunk.id}: {e}")

    return questions_created


# =========================================================================
# Master Orchestrator
# =========================================================================

async def run_full_pipeline(website_id: int) -> dict:
    """Executes the complete pipeline with status tracking on the Website model."""
    async with async_session() as session:
        website = await session.get(Website, website_id)
        if not website:
            raise ValueError(f"Website with id {website_id} not found")

        website.status = WebsiteScrapeStatus.IN_PROGRESS
        website.error_message = None
        await session.commit()

        org_id = website.org_id
        base_url = website.url

    try:
        # Stage 1: URL Discovery
        discovered_urls = await run_discovery(org_id=org_id, web_id=website_id, base_url=base_url)

        # Stage 2: Page Scraping
        scraped_pages = await scrape_pending_pages(web_id=website_id)

        # Stage 3: Content Chunking
        created_chunks = await chunk_completed_pages(web_id=website_id)

        # Stage 4: Question Generation
        generated_questions = await generate_questions_for_chunks(web_id=website_id)

        async with async_session() as session:
            website = await session.get(Website, website_id)
            website.status = WebsiteScrapeStatus.COMPLETED
            await session.commit()

        return {
            "status": "COMPLETED",
            "discovered_urls": discovered_urls,
            "scraped_pages": scraped_pages,
            "created_chunks": created_chunks,
            "generated_questions": generated_questions,
        }

    except Exception as e:
        async with async_session() as session:
            website = await session.get(Website, website_id)
            if website:
                website.status = WebsiteScrapeStatus.FAILED
                website.error_message = str(e)
                await session.commit()
        raise e