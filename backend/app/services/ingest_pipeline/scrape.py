import asyncio
import os
import re
from pathlib import Path
from typing import List, Optional
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BASE_OUTPUT_DIR = BASE_DIR / "data" / "knowledge_base"


def sanitize_filename(url: str) -> str:
    """Creates a filesystem-safe Markdown filename from a URL."""
    clean_name = re.sub(r"https?://", "", url)
    clean_name = re.sub(r"[^\w\-]", "_", clean_name)
    return clean_name[:100] + ".md"


async def scrape_site(
    start_url: str,
    tenant_id: str,
    max_depth: int = 2,
    output_dir: Optional[Path] = None,
) -> List[Path]:
    """
    Crawls a target website, saves raw Markdown files scoped by tenant,
    and returns the paths to all saved markdown documents.
    """
    target_dir = (output_dir or BASE_OUTPUT_DIR) / tenant_id
    target_dir.mkdir(parents=True, exist_ok=True)

    config = CrawlerRunConfig(
        deep_crawl_strategy=BFSDeepCrawlStrategy(
            max_depth=max_depth,
            include_external=False,
        ),
        cache_mode=CacheMode.BYPASS,
        excluded_tags=["nav", "footer", "header", "script", "style"],
    )

    print(f"[{tenant_id}] Starting crawl on: {start_url} (depth={max_depth})...")
    saved_filepaths: List[Path] = []

    async with AsyncWebCrawler() as crawler:
        results = await crawler.arun(url=start_url, config=config)

        for result in results:
            if result.success and result.markdown:
                filename = sanitize_filename(result.url)
                filepath = target_dir / filename

                content = (
                    f"---\n"
                    f"tenant_id: {tenant_id}\n"
                    f"source_url: {result.url}\n"
                    f"---\n\n"
                    f"{result.markdown}"
                )

                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)

                saved_filepaths.append(filepath)

    print(f"[{tenant_id}] Completed crawl. Saved {len(saved_filepaths)} pages to '{target_dir}'.")
    return saved_filepaths


if __name__ == "__main__":
    # Test execution for standalone manual runs
    asyncio.run(
        scrape_site(
            start_url="https://mseuf.edu.ph",
            tenant_id="mseuf",
            max_depth=2,
        )
    )