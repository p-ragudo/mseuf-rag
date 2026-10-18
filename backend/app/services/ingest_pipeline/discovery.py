import xml.etree.ElementTree as ET
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from datetime import datetime, timezone

import httpx
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from sqlalchemy.dialects.postgresql import insert

from app.core.database import async_session
from app.models.scraped_page import ScrapedPage, PageProcessStatus

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl().rstrip("/")


def _is_crawl_trap(url: str) -> bool:
    """
    Blocks infinite calendar query loops, filters, and dynamic pagination traps.
    e.g. /events?view=2025-05, /calendar?month=...
    """
    parsed = urlparse(url)
    query = parsed.query.lower()
    path = parsed.path.lower()

    # Block recursive calendar/events queries
    trap_params = ["view=", "month=", "year=", "date=", "filter=", "calendar_"]
    if any(param in query for param in trap_params):
        return True

    # Block media / binary downloads discovered accidentally
    ignored_extensions = (
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".zip",
        ".docx", ".xlsx", ".pptx", ".mp4", ".svg"
    )
    if any(path.endswith(ext) for ext in ignored_extensions):
        return True

    return False


async def _fetch_sitemap_urls(
    client: httpx.AsyncClient,
    sitemap_url: str,
    visited_sitemaps: Set[str],
) -> Set[str]:
    clean_sitemap_url = _normalize_url(sitemap_url)
    if clean_sitemap_url in visited_sitemaps:
        return set()

    visited_sitemaps.add(clean_sitemap_url)
    discovered: Set[str] = set()

    try:
        resp = await client.get(clean_sitemap_url, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200 or not resp.text.strip():
            return discovered

        root = ET.fromstring(resp.text)
        namespace = {"ns": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}

        # Sitemap index
        sitemap_tags = (
            root.findall(".//ns:sitemap/ns:loc", namespace)
            if namespace
            else root.findall(".//sitemap/loc")
        )
        if sitemap_tags:
            for tag in sitemap_tags:
                if tag.text:
                    child_urls = await _fetch_sitemap_urls(
                        client, tag.text.strip(), visited_sitemaps
                    )
                    discovered.update(child_urls)
            return discovered

        # Direct page URLs
        url_tags = (
            root.findall(".//ns:url/ns:loc", namespace)
            if namespace
            else root.findall(".//url/loc")
        )
        for tag in url_tags:
            if tag.text:
                norm = _normalize_url(tag.text.strip())
                if not _is_crawl_trap(norm):
                    discovered.add(norm)

    except Exception:
        pass

    return discovered


async def _discover_from_sitemaps(
    base_url: str,
    robot_parser: Optional[RobotFileParser] = None,
) -> Set[str]:
    parsed = urlparse(base_url)
    root_origin = f"{parsed.scheme}://{parsed.netloc}"
    discovered: Set[str] = set()
    candidate_sitemaps: List[str] = []
    visited_sitemaps: Set[str] = set()

    async with httpx.AsyncClient(headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
        try:
            robots_resp = await client.get(
                f"{root_origin}/robots.txt", timeout=10.0, follow_redirects=True
            )
            if robots_resp.status_code == 200:
                for line in robots_resp.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        candidate_sitemaps.append(line.split(":", 1)[1].strip())
        except Exception:
            pass

        candidate_sitemaps.extend([
            f"{root_origin}/sitemap.xml",
            f"{root_origin}/sitemap_index.xml",
            f"{root_origin}/wp-sitemap.xml",
        ])

        for sm_url in list(dict.fromkeys(candidate_sitemaps)):
            urls = await _fetch_sitemap_urls(client, sm_url, visited_sitemaps)
            discovered.update(urls)

    if robot_parser:
        discovered = {
            url for url in discovered if robot_parser.can_fetch(DEFAULT_USER_AGENT, url)
        }

    return discovered


async def _discover_from_internal_links(
    base_url: str,
    robot_parser: Optional[RobotFileParser] = None,
) -> Set[str]:
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
                    clean = _normalize_url(full_url)
                    if not _is_crawl_trap(clean):
                        if not robot_parser or robot_parser.can_fetch(DEFAULT_USER_AGENT, clean):
                            found.add(clean)

    return found


async def _get_robot_parser(base_url: str) -> RobotFileParser:
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()

    try:
        async with httpx.AsyncClient(headers={"User-Agent": DEFAULT_USER_AGENT}) as client:
            resp = await client.get(robots_url, timeout=10.0, follow_redirects=True)
            if resp.status_code == 200:
                parser.parse(resp.text.splitlines())
            else:
                parser.allow_all = True
    except Exception:
        parser.allow_all = True

    return parser


async def run_discovery(
    org_id: int, 
    web_id: int, 
    base_url: str,
    max_pages: Optional[int] = None,
) -> int:
    clean_base = _normalize_url(base_url)
    robot_parser = await _get_robot_parser(clean_base)

    urls = await _discover_from_sitemaps(clean_base, robot_parser=robot_parser)
    if not urls:
        urls = await _discover_from_internal_links(clean_base, robot_parser=robot_parser)

    if robot_parser.can_fetch(DEFAULT_USER_AGENT, clean_base):
        urls.add(clean_base)

    filtered_urls = [u for u in urls if not _is_crawl_trap(u)]
    if not filtered_urls:
        return 0

    sorted_urls = sorted(filtered_urls)
    if max_pages and max_pages > 0 and len(sorted_urls) > max_pages:
        sorted_urls = [clean_base] + [u for u in sorted_urls if u != clean_base][:max_pages - 1]

    records = [
        {
            "org_id": org_id,
            "web_id": web_id,
            "url": target_url,
            "markdown_content": None,
            "status": PageProcessStatus.PENDING,
            "retries": 0,
        }
        for target_url in sorted_urls
    ]

    now = datetime.now(timezone.utc)
    BATCH_SIZE = 200

    async with async_session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = [{**r, "last_seen_at": now} for r in records[i:i + BATCH_SIZE]]
            stmt = (
                insert(ScrapedPage)
                .values(batch)
                .on_conflict_do_update(
                    index_elements=["org_id", "web_id", "url"],
                    set_={"last_seen_at": now},
                )
            )
            await session.execute(stmt)
            await session.commit()

    # total URLs discovered this run (used by the purge safety guard), not only new ones
    return len(sorted_urls)