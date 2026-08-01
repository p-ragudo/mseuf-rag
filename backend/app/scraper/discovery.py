import csv
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET
import requests
import os
from dotenv import load_dotenv

load_dotenv()

# 1. Base Setup & Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DISCOVERY_DIR = BASE_DIR / "data" / "discovery"
RAW_SITEMAP_DIR = DISCOVERY_DIR / "raw_sitemaps"

DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
RAW_SITEMAP_DIR.mkdir(parents=True, exist_ok=True)

TARGET_DOMAIN = os.getenv("TARGET_DOMAIN")
ROBOTS_URL = f"{TARGET_DOMAIN}/robots.txt"
USER_AGENT = "ThesisScraperBot/1.0"


def fetch_robots_txt():
    """Fetches robots.txt, saves it raw, parses allow/disallow rules,

    and returns (sitemap_urls, is_allowed_func).
    """
    print(f"[+] Fetching {ROBOTS_URL}...")
    resp = requests.get(ROBOTS_URL, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()

    # Save raw robots.txt
    robots_file = DISCOVERY_DIR / "robots.txt"
    robots_file.write_text(resp.text, encoding="utf-8")
    print(f"    Saved raw robots.txt to {robots_file}")

    # Extract Sitemap URLs from robots.txt
    sitemaps = []
    for line in resp.text.splitlines():
        if line.strip().lower().startswith("sitemap:"):
            parts = line.split(":", 1)
            if len(parts) > 1:
                sitemaps.append(parts[1].strip())

    rp = RobotFileParser()
    rp.parse(resp.text.splitlines())

    def is_allowed(url: str) -> bool:
        return rp.can_fetch(USER_AGENT, url) or rp.can_fetch("*", url)

    return sitemaps, is_allowed


def fetch_and_parse_sitemap(
    sitemap_url: str, visited_sitemaps: set = None
) -> list[dict]:
    """Recursively downloads and parses XML sitemaps.

    Handles both standard sitemaps and .xml sitemap URLs hidden inside <url> tags.
    """
    if visited_sitemaps is None:
        visited_sitemaps = set()

    # Prevent infinite recursive loops
    if sitemap_url in visited_sitemaps:
        return []
    visited_sitemaps.add(sitemap_url)

    filename = sitemap_url.split("/")[-1] or "sitemap.xml"
    raw_path = RAW_SITEMAP_DIR / filename

    print(f"[+] Fetching sitemap: {sitemap_url}...")
    try:
        resp = requests.get(
            sitemap_url, headers={"User-Agent": USER_AGENT}, timeout=15
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    [!] Failed to fetch {sitemap_url}: {e}")
        return []

    # Save raw XML file locally
    raw_path.write_text(resp.text, encoding="utf-8")

    urls_data = []

    try:
        root = ET.fromstring(resp.content)

        # Strip XML namespaces for easy element finding
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}", 1)[1]

        # Check all <url> entries
        for url_node in root.findall(".//url"):
            loc = url_node.find("loc")
            lastmod = url_node.find("lastmod")
            changefreq = url_node.find("changefreq")

            if loc is not None and loc.text:
                target_url = loc.text.strip()

                # CATCH THE CMS PATTERN: If the URL is another XML sitemap, recurse!
                if target_url.endswith(".xml") or ".xml?" in target_url:
                    print(
                        f"    [↳] Discovered nested sitemap inside <url>: {target_url}"
                    )
                    nested_records = fetch_and_parse_sitemap(
                        target_url, visited_sitemaps
                    )
                    urls_data.extend(nested_records)
                else:
                    urls_data.append(
                        {
                            "url": target_url,
                            "lastmod": lastmod.text.strip()
                            if lastmod is not None and lastmod.text
                            else None,
                            "changefreq": changefreq.text.strip()
                            if changefreq is not None and changefreq.text
                            else None,
                            "source_sitemap": filename,
                        }
                    )

    except ET.ParseError as e:
        print(f"    [!] Error parsing XML for {sitemap_url}: {e}")

    return urls_data


def assign_bucket(url: str) -> str:
    """Classifies a URL into a path pattern bucket."""
    path = urlparse(url).path.strip("/")
    if not path:
        return "/"

    parts = path.split("/")
    first_segment = parts[0]

    known_buckets = [
        "news",
        "programs",
        "scholarships",
        "pages",
        "events",
        "announcements",
        "research",
        "careers",
        "academic-departments",
        "offices",
        "sustainability",
    ]

    if first_segment in known_buckets:
        return f"/{first_segment}/*"

    return f"/{first_segment}/*" if len(parts) > 1 else f"/{first_segment}"


def run_discovery():
    # 1. Get Sitemaps from Robots.txt
    sitemap_urls, is_allowed = fetch_robots_txt()

    all_raw_records = []
    visited_sitemaps = set()

    # 2. Recursively parse all sitemaps
    for sitemap_url in sitemap_urls:
        records = fetch_and_parse_sitemap(sitemap_url, visited_sitemaps)
        all_raw_records.extend(records)

    # Deduplicate records by URL
    unique_records = {r["url"]: r for r in all_raw_records}.values()

    allowed_url_records = []
    disallowed_url_records = []

    # 3. Filter using robots.txt rules
    for record in unique_records:
        if is_allowed(record["url"]):
            allowed_url_records.append(record)
        else:
            record["status"] = "disallowed_by_robots"
            disallowed_url_records.append(record)

    # 4. Add bucket classifications
    bucket_counts = {}
    for record in allowed_url_records:
        bucket = assign_bucket(record["url"])
        record["bucket"] = bucket
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    # 5. Save output files
    allowed_out = DISCOVERY_DIR / "allowed_url_inventory.json"
    with open(allowed_out, "w", encoding="utf-8") as f:
        json.dump(allowed_url_records, f, indent=2)
    print(
        f"\n[✔] Saved {len(allowed_url_records)} allowed target URLs: {allowed_out}"
    )

    disallowed_out = DISCOVERY_DIR / "disallowed_url_inventory.json"
    with open(disallowed_out, "w", encoding="utf-8") as f:
        json.dump(disallowed_url_records, f, indent=2)
    print(
        f"[✔] Saved {len(disallowed_url_records)} disallowed URLs log: {disallowed_out}"
    )

    csv_out = DISCOVERY_DIR / "bucket_summary.csv"
    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["Bucket Pattern", "URL Count", "Sample URL", "Source Sitemap"]
        )

        for bucket, count in bucket_counts.items():
            sample = next(
                r for r in allowed_url_records if r["bucket"] == bucket
            )
            writer.writerow(
                [bucket, count, sample["url"], sample["source_sitemap"]]
            )

    print(f"[✔] Saved bucket summary CSV: {csv_out}\n")


if __name__ == "__main__":
    run_discovery()