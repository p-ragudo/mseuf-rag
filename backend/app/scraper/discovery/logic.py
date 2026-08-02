"""
Pure logic: everything that transforms data without touching the network or disk.

Every function here takes plain values in and returns plain values out - no requests,
no file writes, no side effects. This is what makes them trivial to test: call the
function, assert on the return value, done. No mocking, no monkeypatching, no tmp_path.

Sections, top to bottom, in pipeline order:
    - robots.txt parsing
    - sitemap XML parsing
    - record-level transforms (dedupe, filter by robots rules)
    - bucketing (grouping URLs by first path segment)
"""

import xml.etree.ElementTree as ET
from typing import Callable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .config import USER_AGENT


# =========================================================================
# robots.txt parsing
# =========================================================================

def parse_robots_txt(text: str) -> tuple[list[str], Callable[[str], bool]]:
    """
    Parses robots.txt text into (sitemap_urls, is_allowed_fn).
    is_allowed_fn(url) -> bool, checks against both our USER_AGENT and '*' rules.
    """
    sitemap_urls = []
    for line in text.splitlines():
        if line.strip().lower().startswith("sitemap:"):
            parts = line.split(":", 1)
            if len(parts) > 1:
                sitemap_urls.append(parts[1].strip())

    rp = RobotFileParser()
    rp.parse(text.splitlines())

    def is_allowed(url: str) -> bool:
        return rp.can_fetch(USER_AGENT, url) or rp.can_fetch("*", url)

    return sitemap_urls, is_allowed


# =========================================================================
# Sitemap XML parsing
# =========================================================================

def parse_sitemap_xml(xml_text: str, source_filename: str) -> tuple[list[dict], list[str]]:
    """
    Parses one sitemap XML document into (url_records, nested_sitemap_urls).
    Does not fetch or recurse - interprets a single already-fetched document.
    Raises ET.ParseError on malformed XML.
    """
    url_records = []
    nested_sitemap_urls = []

    root = ET.fromstring(xml_text)

    # Strip XML namespaces so .find()/.findall() work without namespace prefixes
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]

    for url_node in root.findall(".//url"):
        loc = url_node.find("loc")
        lastmod = url_node.find("lastmod")
        changefreq = url_node.find("changefreq")

        if loc is None or not loc.text:
            continue

        target_url = loc.text.strip()

        if target_url.endswith(".xml") or ".xml?" in target_url:
            nested_sitemap_urls.append(target_url)
        else:
            url_records.append({
                "url": target_url,
                "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else None,
                "changefreq": changefreq.text.strip() if changefreq is not None and changefreq.text else None,
                "source_sitemap": source_filename,
            })

    # Example of an item in url_records
    # {
    #     "url": "https://domain.com/news/article-1",
    #     "lastmod": "2026-03-15",
    #     "changefreq": "daily",
    #     "source_sitemap": "sitemap.xml"
    # },        

    return url_records, nested_sitemap_urls



# =========================================================================
# Record-level transforms
# =========================================================================

def dedupe_records(records: list[dict]) -> list[dict]:
    """
    Removes duplicate URL records, keeping the first occurrence of each URL.
    """
    seen = {}
    for r in records:
        if r["url"] not in seen:
            seen[r["url"]] = r
    return list(seen.values())


def partition_by_robots(
    records: list[dict], is_allowed_fn: Callable[[str], bool]
) -> tuple[list[dict], list[dict]]:
    """
    Splits records into (allowed, disallowed) based on robots.txt rules.
    Disallowed records get a 'status' key added; input records are not mutated.
    """
    allowed, disallowed = [], []
    for record in records:
        if is_allowed_fn(record["url"]):
            allowed.append(record)
        else:
            disallowed.append({**record, "status": "disallowed_by_robots"})
    return allowed, disallowed


# =========================================================================
# Bucketing
# =========================================================================
# No hardcoded "known buckets" list - every first path segment is treated
# identically as '/segment/*'. This means new site sections (e.g. a future
# /alumni page nobody configured for) still bucket correctly with zero changes.

def assign_bucket(url: str) -> str:
    """
    Classifies a URL by its first path segment. Root path returns '/'.
    """
    path = urlparse(url).path.strip("/")
    if not path:
        return "/"
    first_segment = path.split("/")[0]
    return f"/{first_segment}/*"


def build_bucket_summary(records: list[dict]) -> list[dict]:
    """
    Groups records by bucket, returning one summary row per bucket.
    Each row: {bucket, count, sample_url, source_sitemap}.
    Mutates each record in place to add a 'bucket' key.
    """
    bucket_counts: dict[str, int] = {}
    bucket_sample: dict[str, dict] = {}

    for record in records:
        bucket = assign_bucket(record["url"])
        record["bucket"] = bucket
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        if bucket not in bucket_sample:
            bucket_sample[bucket] = record

    return [
        {
            "bucket": bucket,
            "count": count,
            "sample_url": bucket_sample[bucket]["url"],
            "source_sitemap": bucket_sample[bucket]["source_sitemap"],
        }
        for bucket, count in bucket_counts.items()
    ]
