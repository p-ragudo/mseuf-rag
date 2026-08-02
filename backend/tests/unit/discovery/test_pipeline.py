"""
Tests for pipeline.py: crawling and orchestration.

fetch_fn / save_fn are always replaced with plain Python functions/lambdas that
read from an in-memory dict instead of hitting the network or disk. This is what
lets these tests run instantly and deterministically while still exercising the
real recursion, cycle-detection, and dedup logic exactly as production runs it.
"""

import requests
import os
from dotenv import load_dotenv

from app.scraper.discovery.pipeline import (
    SitemapCrawlResult,
    crawl_all_sitemaps,
    crawl_sitemap_tree,
    run_discovery,
)
from .conftest_helpers import make_robots_txt, make_sitemap_xml

load_dotenv()

TEST_TARGET_DOMAIN = os.getenv("TEST_TARGET_DOMAIN")
if not TEST_TARGET_DOMAIN:
    raise ValueError(
        "[!] TEST_TARGET_DOMAIN environment variable is not set in .env file."
    )

class TestCrawlSitemapTree:
    def test_fetches_every_url_across_the_whole_nested_tree(self):
        """
        Verifies: nothing is missing. Every page URL under every level of nesting
        ends up in the result, regardless of how deep it's buried.
        """
        xml_by_url = {
            f"{TEST_TARGET_DOMAIN}/sitemap.xml": make_sitemap_xml(
                urls=[TEST_TARGET_DOMAIN, f"{TEST_TARGET_DOMAIN}/news"],
                nested_sitemaps=[f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml"],
            ),
            f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml": make_sitemap_xml(
                urls=[f"{TEST_TARGET_DOMAIN}/post-1", f"{TEST_TARGET_DOMAIN}/post-2"],
                nested_sitemaps=[f"{TEST_TARGET_DOMAIN}/sitemap_programs.xml"],  # 2 levels deep
            ),
            f"{TEST_TARGET_DOMAIN}/sitemap_programs.xml": make_sitemap_xml(
                urls=[f"{TEST_TARGET_DOMAIN}/programs/bscs"],
            ),
        }
        result = SitemapCrawlResult()
        crawl_sitemap_tree(
            f"{TEST_TARGET_DOMAIN}/sitemap.xml",
            result,
            fetch_fn=lambda url: xml_by_url[url],
            save_fn=lambda filename, content: None,
        )

        fetched_urls = {r["url"] for r in result.url_records}
        assert fetched_urls == {
            f"{TEST_TARGET_DOMAIN}",
            f"{TEST_TARGET_DOMAIN}/news",
            f"{TEST_TARGET_DOMAIN}/post-1",
            f"{TEST_TARGET_DOMAIN}/post-2",
            f"{TEST_TARGET_DOMAIN}/programs/bscs",
        }
        # exact count match, not just "contains" - proves nothing extra snuck in either
        assert len(result.url_records) == 5

    def test_skips_already_visited_sitemap_on_cyclical_reference(self):
        """
        Verifies: a sitemap that links back to an ancestor is fetched exactly once,
        not re-fetched and not causing infinite recursion.
        """
        xml_by_url = {
            f"{TEST_TARGET_DOMAIN}/sitemap.xml": make_sitemap_xml(
                nested_sitemaps=[f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml"],
            ),
            f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml": make_sitemap_xml(
                urls=[f"{TEST_TARGET_DOMAIN}/post-1"],
                nested_sitemaps=[f"{TEST_TARGET_DOMAIN}/sitemap.xml"],  # cycle back to parent
            ),
        }
        fetch_calls = []

        def fake_fetch(url):
            fetch_calls.append(url)
            return xml_by_url[url]

        result = SitemapCrawlResult()
        crawl_sitemap_tree(
            f"{TEST_TARGET_DOMAIN}/sitemap.xml",
            result,
            fetch_fn=fake_fetch,
            save_fn=lambda filename, content: None,
        )

        # each sitemap URL was fetched exactly once, despite the cycle
        assert fetch_calls.count(f"{TEST_TARGET_DOMAIN}/sitemap.xml") == 1
        assert fetch_calls.count(f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml") == 1
        assert result.visited_sitemaps == {
            f"{TEST_TARGET_DOMAIN}/sitemap.xml",
            f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml",
        }
        # test completing at all (not hanging) proves no infinite recursion happened

    def test_discovers_nested_sitemap_not_present_in_robots_txt(self):
        """
        Mirrors the real case: sitemap_sustainability.xml is nested inside
        sitemap.xml but never listed as a Sitemap: line in robots.txt itself.
        """
        xml_by_url = {
            f"{TEST_TARGET_DOMAIN}/sitemap.xml": make_sitemap_xml(
                nested_sitemaps=[f"{TEST_TARGET_DOMAIN}/sitemap_sustainability.xml"],
            ),
            f"{TEST_TARGET_DOMAIN}/sitemap_sustainability.xml": make_sitemap_xml(
                urls=[f"{TEST_TARGET_DOMAIN}/sustainability/green-campus"],
            ),
        }
        result = SitemapCrawlResult()
        crawl_sitemap_tree(
            f"{TEST_TARGET_DOMAIN}/sitemap.xml",
            result,
            fetch_fn=lambda url: xml_by_url[url],
            save_fn=lambda filename, content: None,
        )
        assert f"{TEST_TARGET_DOMAIN}/sustainability/green-campus" in {r["url"] for r in result.url_records}
        assert f"{TEST_TARGET_DOMAIN}/sitemap_sustainability.xml" in result.visited_sitemaps

    def test_records_exact_url_count_per_individual_sitemap(self):
        """
        This is the per-sitemap audit trail: for each sitemap URL, how many
        <url> entries did IT directly contain (not counting nested sitemaps' URLs).
        """
        xml_by_url = {
            f"{TEST_TARGET_DOMAIN}/sitemap.xml": make_sitemap_xml(
                urls=[f"{TEST_TARGET_DOMAIN}", f"{TEST_TARGET_DOMAIN}/news"],
                nested_sitemaps=[f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml"],
            ),
            f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml": make_sitemap_xml(
                urls=[f"{TEST_TARGET_DOMAIN}/post-1", f"{TEST_TARGET_DOMAIN}/post-2", f"{TEST_TARGET_DOMAIN}/post-3"],
            ),
        }
        result = SitemapCrawlResult()
        crawl_sitemap_tree(
            f"{TEST_TARGET_DOMAIN}/sitemap.xml",
            result,
            fetch_fn=lambda url: xml_by_url[url],
            save_fn=lambda filename, content: None,
        )
        assert result.sitemap_url_counts == {
            f"{TEST_TARGET_DOMAIN}/sitemap.xml": 2,
            f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml": 3,
        }
        # cross-check: sum of per-sitemap counts equals total records collected
        assert sum(result.sitemap_url_counts.values()) == len(result.url_records)

    def test_network_failure_on_one_sitemap_does_not_stop_the_rest(self):
        """
        Verifies partial failures are tracked, not silently swallowed or fatal.
        """
        xml_by_url = {
            f"{TEST_TARGET_DOMAIN}/sitemap.xml": make_sitemap_xml(
                nested_sitemaps=[
                    f"{TEST_TARGET_DOMAIN}/sitemap_broken.xml",
                    f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml",
                ],
            ),
            f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml": make_sitemap_xml(urls=[f"{TEST_TARGET_DOMAIN}/post-1"]),
        }

        def flaky_fetch(url):
            if "broken" in url:
                raise requests.RequestException("simulated 404")
            return xml_by_url[url]

        result = SitemapCrawlResult()
        crawl_sitemap_tree(
            f"{TEST_TARGET_DOMAIN}/sitemap.xml",
            result,
            fetch_fn=flaky_fetch,
            save_fn=lambda filename, content: None,
        )
        assert result.failed_sitemaps == [f"{TEST_TARGET_DOMAIN}/sitemap_broken.xml"]
        # the OTHER branch still succeeded despite the failure
        assert f"{TEST_TARGET_DOMAIN}/post-1" in {r["url"] for r in result.url_records}


class TestCrawlAllSitemaps:
    def test_two_seed_sitemaps_sharing_a_nested_sitemap_fetch_it_only_once(self):
        xml_by_url = {
            f"{TEST_TARGET_DOMAIN}/sitemap.xml": make_sitemap_xml(
                urls=[f"{TEST_TARGET_DOMAIN}/news"],
                nested_sitemaps=[f"{TEST_TARGET_DOMAIN}/sitemap_shared.xml"],
            ),
            f"{TEST_TARGET_DOMAIN}/sitemap_programs.xml": make_sitemap_xml(
                urls=[f"{TEST_TARGET_DOMAIN}/programs"],
                nested_sitemaps=[f"{TEST_TARGET_DOMAIN}/sitemap_shared.xml"],  # same nested ref
            ),
            f"{TEST_TARGET_DOMAIN}/sitemap_shared.xml": make_sitemap_xml(
                urls=[f"{TEST_TARGET_DOMAIN}/shared-page"],
            ),
        }
        fetch_calls = []

        def fake_fetch(url):
            fetch_calls.append(url)
            return xml_by_url[url]

        result = crawl_all_sitemaps(
            [f"{TEST_TARGET_DOMAIN}/sitemap.xml", f"{TEST_TARGET_DOMAIN}/sitemap_programs.xml"],
            fetch_fn=fake_fetch,
            save_fn=lambda filename, content: None,
        )

        assert fetch_calls.count(f"{TEST_TARGET_DOMAIN}/sitemap_shared.xml") == 1
        assert len(result.url_records) == 3  # news, programs, shared-page - not duplicated


class TestRunDiscoveryEndToEnd:
    def test_full_pipeline_fetch_coverage_dedup_and_bucket_counts_all_at_once(self):
        """
        The single test that answers all three of your original questions together,
        run through the exact same code path as production (just with fake I/O):
          1. Did it fetch every allowed URL?                -> allowed_urls set check
          2. Did it correctly skip/collapse duplicates?     -> raw vs unique count check
          3. Are per-bucket counts exact?                   -> bucket_counts dict check
        """
        robots_text = make_robots_txt(
            [f"{TEST_TARGET_DOMAIN}/sitemap.xml", f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml"],
            disallow_paths=["/admin"],
        )

        xml_by_url = {
            f"{TEST_TARGET_DOMAIN}/sitemap.xml": make_sitemap_xml(
                urls=[
                    f"{TEST_TARGET_DOMAIN}/news",
                    f"{TEST_TARGET_DOMAIN}/news/article-1",  # will also appear in sitemap_posts.xml
                    f"{TEST_TARGET_DOMAIN}/admin/secret",     # will be filtered by robots.txt
                ],
            ),
            f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml": make_sitemap_xml(
                urls=[
                    f"{TEST_TARGET_DOMAIN}/news/article-1",  # duplicate of above
                    f"{TEST_TARGET_DOMAIN}/news/article-2",
                    f"{TEST_TARGET_DOMAIN}/programs",
                ],
            ),
        }

        saved_json = {}
        saved_csv = {}

        summary = run_discovery(
            fetch_robots_fn=lambda url: robots_text,
            save_robots_fn=lambda content: None,
            fetch_sitemap_fn=lambda url: xml_by_url[url],
            save_sitemap_fn=lambda filename, content: None,
            save_json_fn=lambda records, path: saved_json.__setitem__(path.name, records),
            save_csv_fn=lambda rows, path: saved_csv.__setitem__(path.name, rows),
        )

        # --- 1. All allowed URLs were fetched, none missing ---
        allowed_urls = {r["url"] for r in saved_json["allowed_url_inventory.json"]}
        assert allowed_urls == {
            f"{TEST_TARGET_DOMAIN}/news",
            f"{TEST_TARGET_DOMAIN}/news/article-1",
            f"{TEST_TARGET_DOMAIN}/news/article-2",
            f"{TEST_TARGET_DOMAIN}/programs",
        }

        # --- 2. Duplicate was correctly collapsed: 6 raw records in, 5 unique out ---
        assert summary["total_raw_records"] == 6
        assert summary["total_unique_records"] == 5
        assert len(allowed_urls) == 4  # 5 unique minus 1 disallowed (admin)

        # --- 2b. Disallowed URL correctly excluded, not silently dropped elsewhere ---
        disallowed_urls = {r["url"] for r in saved_json["disallowed_url_inventory.json"]}
        assert disallowed_urls == {f"{TEST_TARGET_DOMAIN}/admin/secret"}

        # --- 3. Exact per-bucket counts ---
        bucket_counts = {row["bucket"]: row["count"] for row in saved_csv["bucket_summary.csv"]}
        assert bucket_counts == {
            "/news/*": 3,      # news, news/article-1, news/article-2
            "/programs/*": 1,  # programs
        }
        # cross-check against the earlier assertions - these numbers must agree
        assert sum(bucket_counts.values()) == len(allowed_urls)

        # --- Both seed sitemaps were actually crawled ---
        assert set(summary["sitemaps_crawled"]) == {
            f"{TEST_TARGET_DOMAIN}/sitemap.xml",
            f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml",
        }
