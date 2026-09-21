import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
from typing import List, Set
import httpx
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from sqlalchemy import select
from app.core.database import async_session_factory
from app.models.scraped_page import ScrapedPage, PageProcessStatus


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    # Strip fragment (#) and trailing slashes
    clean = parsed._replace(fragment="").geturl().rstrip("/")
    return clean


async def _fetch_sitemap_urls(client: httpx.AsyncClient, sitemap_url: str) -> Set[str]:
    """Recursively parses XML sitemaps and nested sitemapindexes."""
    discovered: Set[str] = set()
    try:
        resp = await client.get(sitemap_url, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200 or not resp.text.strip():
            return discovered

        root = ET.fromstring(resp.text)
        namespace = {"ns": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}

        # 1. Check if this is a sitemap index referencing other sitemaps
        sitemap_tags = root.findall(".//ns:sitemap/ns:loc", namespace) if namespace else root.findall(".//sitemap/loc")
        if sitemap_tags:
            for tag in sitemap_tags:
                if tag.text:
                    child_urls = await _fetch_sitemap_urls(client, tag.text.strip())
                    discovered.update(child_urls)
            return discovered

        # 2. Standard sitemap containing page URLs
        url_tags = root.findall(".//ns:url/ns:loc", namespace) if namespace else root.findall(".//url/loc")
        for tag in url_tags:
            if tag.text:
                discovered.add(_normalize_url(tag.text.strip()))

    except Exception:
        pass

    return discovered


async def _discover_from_sitemaps(base_url: str) -> Set[str]:
    """Tries robots.txt sitemap directives, then standard /sitemap.xml fallbacks."""
    parsed = urlparse(base_url)
    root_origin = f"{parsed.scheme}://{parsed.netloc}"
    discovered: Set[str] = set()

    candidate_sitemaps: List[str] = []

    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        # Check robots.txt for Sitemap directives
        try:
            robots_resp = await client.get(f"{root_origin}/robots.txt", timeout=10.0, follow_redirects=True)
            if robots_resp.status_code == 200:
                for line in robots_resp.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        candidate_sitemaps.append(line.split(":", 1)[1].strip())
        except Exception:
            pass

        # Standard sitemap path conventions
        candidate_sitemaps.extend([
            f"{root_origin}/sitemap.xml",
            f"{root_origin}/sitemap_index.xml",
            f"{root_origin}/wp-sitemap.xml",
        ])

        for sm_url in dict.fromkeys(candidate_sitemaps):
            urls = await _fetch_sitemap_urls(client, sm_url)
            if urls:
                discovered.update(urls)
                break  # Stop once a working sitemap is found and parsed

    return discovered


async def _discover_from_internal_links(base_url: str) -> Set[str]:
    """Fallback: Crawl base_url and collect internal hyperlinks."""
    domain = urlparse(base_url).netloc
    found: Set[str] = set()

    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=base_url, config=config)
        if result.success and result.links:
            for item in result.links.get("internal", []):
                href = item.get("href")
                if not href:
                    continue
                full_url = urljoin(base_url, href)
                if urlparse(full_url).netloc == domain:
                    found.add(_normalize_url(full_url))

    return found


async def run_discovery(org_id: int, web_id: int, base_url: str) -> int:
    """
    Finds all URLs on a website via sitemap (falling back to internal links)
    and saves them to scraped_pages with status=PENDING.
    Returns the count of newly inserted URLs.
    """
    clean_base = _normalize_url(base_url)
    urls = await _discover_from_sitemaps(clean_base)

    if not urls:
        urls = await _discover_from_internal_links(clean_base)

    # Ensure the root page is always part of the set
    urls.add(clean_base)

    new_inserts = 0
    async with async_session_factory() as session:
        for url in urls:
            stmt = select(ScrapedPage.id).where(
                ScrapedPage.org_id == org_id,
                ScrapedPage.web_id == web_id,
                ScrapedPage.url == url,
            )
            res = await session.execute(stmt)
            if res.scalar_one_or_none() is None:
                new_page = ScrapedPage(
                    org_id=org_id,
                    web_id=web_id,
                    url=url,
                    markdown_content=None,
                    status=PageProcessStatus.PENDING,
                    retries=0,
                )
                session.add(new_page)
                new_inserts += 1

        await session.commit()

    return new_inserts