"""
I/O and orchestration: fetching, saving, crawling, and the top-level pipeline.

These are kept in one file deliberately, unlike the pure logic in logic.py. Splitting
"fetch a sitemap" from "recursively crawl sitemaps calling fetch" into separate files
added file-jumping cost without adding testability - the crawler's whole job IS
coordinating I/O, so they belong together. Testability comes from dependency
injection instead: every function that touches the network or disk accepts its
I/O as an argument (fetch_fn, save_fn, ...), defaulting to the real thing in
production but swappable with a plain Python function/lambda in tests.

Sections, top to bottom:
    - I/O boundary functions (one network/disk op each - fetch_*, save_*)
    - SitemapCrawlResult + crawler (recursion, cycle-prevention)
    - run_discovery (the one function that wires everything - logic.py + this file - together)
"""

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import requests
import xml.etree.ElementTree as ET

from .config import DISCOVERY_DIR, RAW_SITEMAP_DIR, ROBOTS_URL, USER_AGENT
from .logic import (
    build_bucket_summary,
    dedupe_records,
    parse_robots_txt,
    parse_sitemap_xml,
    partition_by_robots,
)


# =========================================================================
# I/O boundary functions - one network or disk operation each
# =========================================================================

def fetch_robots_txt_content(url: str) -> str:
    """
    Fetches robots.txt raw text from a URL. Raises requests.RequestException on failure.
    """
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    return resp.text


def save_robots_txt(content: str, target_dir: Path = DISCOVERY_DIR) -> Path:
    """
    Writes raw robots.txt to disk, returns the path written.
    """
    path = target_dir / "robots.txt"
    path.write_text(content, encoding="utf-8")
    return path


def fetch_sitemap_content(url: str) -> str:
    """
    Fetches raw sitemap XML text from a URL. Raises requests.RequestException on failure.
    """
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    return resp.text


def save_raw_sitemap(filename: str, content: str, target_dir: Path = RAW_SITEMAP_DIR) -> Path:
    """
    Writes raw sitemap XML to disk, returns the path written.
    """
    path = target_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def save_json(records: list[dict], path: Path) -> Path:
    """
    Writes a list of dict records to a JSON file.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    return path


def save_bucket_summary_csv(rows: list[dict], path: Path) -> Path:
    """
    Writes bucket summary rows to a CSV file.
    """
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Bucket Pattern", "URL Count", "Sample URL", "Source Sitemap"])
        for row in rows:
            writer.writerow([row["bucket"], row["count"], row["sample_url"], row["source_sitemap"]])
    return path


# =========================================================================
# Crawler - recursion + cycle-prevention, delegates fetch/save/parse
# =========================================================================

@dataclass
class SitemapCrawlResult:
    """
    Everything discovered from crawling a sitemap tree.
    """
    url_records: list[dict] = field(default_factory=list)
    sitemap_url_counts: dict[str, int] = field(default_factory=dict)  # sitemap_url -> direct url count
    visited_sitemaps: set = field(default_factory=set)
    failed_sitemaps: list[str] = field(default_factory=list)


def crawl_sitemap_tree(
    sitemap_url: str,
    result: SitemapCrawlResult,
    fetch_fn=fetch_sitemap_content,
    save_fn=save_raw_sitemap,
) -> None:
    """
    Recursively crawls a sitemap and all nested sitemaps, mutating `result` in place.
    
    Skips any sitemap_url already present in result.visited_sitemaps - this is what
    prevents infinite loops and duplicate fetches when sitemaps reference each other
    cyclically or when the same nested sitemap is linked from multiple parents.
    """
    if sitemap_url in result.visited_sitemaps:
        return
    result.visited_sitemaps.add(sitemap_url)

    filename = sitemap_url.split("/")[-1] or "sitemap.xml"

    try:
        xml_text = fetch_fn(sitemap_url)
    except requests.RequestException:
        result.failed_sitemaps.append(sitemap_url)
        return

    save_fn(filename, xml_text)

    try:
        url_records, nested_urls = parse_sitemap_xml(xml_text, filename)
    except ET.ParseError:
        result.failed_sitemaps.append(sitemap_url)
        return

    result.sitemap_url_counts[sitemap_url] = len(url_records)
    result.url_records.extend(url_records)

    for nested_url in nested_urls:
        crawl_sitemap_tree(nested_url, result, fetch_fn, save_fn)


def crawl_all_sitemaps(
    seed_sitemap_urls: list[str],
    fetch_fn=fetch_sitemap_content,
    save_fn=save_raw_sitemap,
) -> SitemapCrawlResult:
    """
    Crawls multiple seed sitemaps (e.g. from robots.txt), deduping visits across all of them.
    """
    result = SitemapCrawlResult()
    for seed_url in seed_sitemap_urls:
        crawl_sitemap_tree(seed_url, result, fetch_fn, save_fn)
    return result


# =========================================================================
# Top-level pipeline - the one function that reads top-to-bottom as "the whole flow"
# =========================================================================

def run_discovery(
    fetch_robots_fn=fetch_robots_txt_content,
    save_robots_fn=save_robots_txt,
    fetch_sitemap_fn=fetch_sitemap_content,
    save_sitemap_fn=save_raw_sitemap,
    save_json_fn=save_json,
    save_csv_fn=save_bucket_summary_csv,
) -> dict:
    """
    Runs the full discovery pipeline: robots.txt -> crawl sitemaps -> dedupe ->
    filter by robots rules -> bucket -> save outputs.

    Returns a summary dict for logging/inspection (also useful as a test seam).
    """
    robots_text = fetch_robots_fn(ROBOTS_URL)
    save_robots_fn(robots_text)

    sitemap_seed_urls, is_allowed = parse_robots_txt(robots_text)

    crawl_result = crawl_all_sitemaps(sitemap_seed_urls, fetch_sitemap_fn, save_sitemap_fn)

    unique_records = dedupe_records(crawl_result.url_records)
    allowed_records, disallowed_records = partition_by_robots(unique_records, is_allowed)
    bucket_summary = build_bucket_summary(allowed_records)  # mutates allowed_records to add 'bucket'

    save_json_fn(allowed_records, DISCOVERY_DIR / "allowed_url_inventory.json")
    save_json_fn(disallowed_records, DISCOVERY_DIR / "disallowed_url_inventory.json")
    save_csv_fn(bucket_summary, DISCOVERY_DIR / "bucket_summary.csv")

    return {
        "total_raw_records": len(crawl_result.url_records),
        "total_unique_records": len(unique_records),
        "total_allowed": len(allowed_records),
        "total_disallowed": len(disallowed_records),
        "sitemaps_crawled": sorted(crawl_result.visited_sitemaps),
        "sitemaps_failed": crawl_result.failed_sitemaps,
        "bucket_summary": bucket_summary,
    }


if __name__ == "__main__":
    summary = run_discovery()
    print(f"[✔] Crawled {len(summary['sitemaps_crawled'])} unique sitemaps")
    print(f"[✔] {summary['total_unique_records']} unique URLs "
          f"({summary['total_allowed']} allowed, {summary['total_disallowed']} disallowed)")
