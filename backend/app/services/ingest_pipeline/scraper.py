import asyncio
from typing import Optional
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from sqlalchemy import select
from app.core.database import async_session_factory
from app.models.scraped_page import ScrapedPage, PageProcessStatus

CRAWL_CONFIG = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,
    excluded_tags=["nav", "footer", "header", "script", "style", "noscript"],
)


async def scrape_single_page(
    page_id: int,
    crawler: Optional[AsyncWebCrawler] = None,
) -> bool:
    """
    1. Marks record IN_PROGRESS.
    2. Runs crawl4ai.
    3. Checkpoints RAW markdown directly to DB as COMPLETED, or marks FAILED on error.
    """
    # 1. Reserve row
    async with async_session_factory() as session:
        page = await session.get(ScrapedPage, page_id)
        if not page:
            raise ValueError(f"ScrapedPage ID {page_id} does not exist.")

        page.status = PageProcessStatus.IN_PROGRESS
        await session.commit()
        target_url = page.url

    # 2. Scrape
    async def _execute_scrape(active_crawler: AsyncWebCrawler) -> tuple[bool, Optional[str]]:
        try:
            result = await active_crawler.arun(url=target_url, config=CRAWL_CONFIG)
            if result.success and result.markdown:
                return True, result.markdown
        except Exception:
            pass
        return False, None

    if crawler:
        success, raw_markdown = await _execute_scrape(crawler)
    else:
        async with AsyncWebCrawler() as local_crawler:
            success, raw_markdown = await _execute_scrape(local_crawler)

    # 3. Checkpoint raw markdown
    async with async_session_factory() as session:
        page = await session.get(ScrapedPage, page_id)
        if page:
            if success and raw_markdown:
                page.markdown_content = raw_markdown
                page.status = PageProcessStatus.COMPLETED
            else:
                page.status = PageProcessStatus.FAILED
                page.retries += 1
            await session.commit()

    return bool(success and raw_markdown)


async def scrape_pending_pages(
    org_id: int,
    web_id: int,
    batch_size: int = 50,
    concurrency_limit: int = 5,
) -> int:
    """Finds PENDING pages and scrapes them concurrently using one shared browser context."""
    async with async_session_factory() as session:
        stmt = (
            select(ScrapedPage.id)
            .where(
                ScrapedPage.org_id == org_id,
                ScrapedPage.web_id == web_id,
                ScrapedPage.status == PageProcessStatus.PENDING,
            )
            .limit(batch_size)
        )
        res = await session.execute(stmt)
        page_ids = list(res.scalars().all())

    if not page_ids:
        return 0

    semaphore = asyncio.Semaphore(concurrency_limit)

    async with AsyncWebCrawler() as shared_crawler:
        async def _bounded_scrape(pid: int):
            async with semaphore:
                return await scrape_single_page(page_id=pid, crawler=shared_crawler)

        tasks = [_bounded_scrape(pid) for pid in page_ids]
        await asyncio.gather(*tasks)

    return len(page_ids)