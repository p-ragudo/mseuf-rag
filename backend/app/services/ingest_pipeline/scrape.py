import asyncio
from typing import List
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

from app.services.sql_db.base import DatabaseRepository
from app.services.sql_db.schema import ScrapedPage


async def scrape_site(
    start_url: str,
    tenant_id: str,
    repo: DatabaseRepository,
    max_depth: int = 2,
) -> List[ScrapedPage]:
    """
    Crawls a target website and checkpoints raw Markdown into Postgres immediately
    as each individual page finishes.
    """
    config = CrawlerRunConfig(
        deep_crawl_strategy=BFSDeepCrawlStrategy(
            max_depth=max_depth,
            include_external=False,
        ),
        cache_mode=CacheMode.BYPASS,
        excluded_tags=["nav", "footer", "header", "script", "style"],
        stream=True,  # Enables streaming execution
    )

    print(f"[{tenant_id}] Starting streaming crawl on: {start_url} (depth={max_depth})...")
    saved_records: List[ScrapedPage] = []

    async with AsyncWebCrawler() as crawler:
        # Stream results one-by-one as each page finishes crawling
        async for result in await crawler.arun(url=start_url, config=config):
            if result.success and result.markdown:
                page_record = ScrapedPage(
                    tenant_id=tenant_id,
                    source_url=result.url,
                    raw_markdown=result.markdown,
                )
                # Immediate write to Postgres after every single completed URL
                saved_page = await repo.upsert_page(page_record)
                saved_records.append(saved_page)
                print(f"[{tenant_id}] Checkpointed page: {result.url}")

    print(f"[{tenant_id}] Completed crawl. Persisted {len(saved_records)} pages.")
    return saved_records


if __name__ == "__main__":
    from app.core.config import settings
    from app.services.sql_db.postgres_provider import PostgresDatabaseRepository

    async def standalone_scrape():
        repo = PostgresDatabaseRepository(dsn=settings.database_url)
        await repo.connect()
        try:
            await scrape_site(
                start_url="https://mseuf.edu.ph",
                tenant_id="mseuf",
                repo=repo,
                max_depth=1,
            )
        finally:
            await repo.close()

    asyncio.run(standalone_scrape())