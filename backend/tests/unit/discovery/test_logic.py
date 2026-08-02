"""
Tests for logic.py: pure functions only. No mocking, no fakes needed here -
every test is plain input -> assert output.
"""

import xml.etree.ElementTree as ET

import pytest
import os
from dotenv import load_dotenv

from app.scraper.discovery.logic import (
    assign_bucket,
    build_bucket_summary,
    dedupe_records,
    parse_robots_txt,
    parse_sitemap_xml,
    partition_by_robots,
)
from .conftest_helpers import make_robots_txt, make_sitemap_xml

load_dotenv()

TEST_TARGET_DOMAIN = os.getenv("TEST_TARGET_DOMAIN")
if not TEST_TARGET_DOMAIN:
    raise ValueError(
        "[!] TEST_TARGET_DOMAIN environment variable is not set in .env file."
    )


class TestParseRobotsTxt:
    def test_extracts_all_sitemap_urls_in_order(self):
        text = make_robots_txt([
            f"{TEST_TARGET_DOMAIN}/sitemap.xml",
            f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml",
            f"{TEST_TARGET_DOMAIN}/sitemap_calendar.xml",
        ])
        sitemap_urls, _ = parse_robots_txt(text)
        assert sitemap_urls == [
            f"{TEST_TARGET_DOMAIN}/sitemap.xml",
            f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml",
            f"{TEST_TARGET_DOMAIN}/sitemap_calendar.xml",
        ]

    def test_is_allowed_respects_disallow_rules(self):
        text = make_robots_txt(
            [f"{TEST_TARGET_DOMAIN}/sitemap.xml"],
            disallow_paths=["/admin"],
        )
        _, is_allowed = parse_robots_txt(text)
        assert is_allowed(f"{TEST_TARGET_DOMAIN}/news") is True
        assert is_allowed(f"{TEST_TARGET_DOMAIN}/admin/login") is False


class TestParseSitemapXml:
    def test_extracts_page_url_records_with_metadata(self):
        xml = make_sitemap_xml(urls=[f"{TEST_TARGET_DOMAIN}/news"])
        records, nested = parse_sitemap_xml(xml, "sitemap.xml")
        assert records == [{
            "url": f"{TEST_TARGET_DOMAIN}/news",
            "lastmod": "2024-01-01",
            "changefreq": None,
            "source_sitemap": "sitemap.xml",
        }]
        assert nested == []

    def test_separates_nested_sitemap_refs_from_page_urls(self):
        xml = make_sitemap_xml(
            urls=[f"{TEST_TARGET_DOMAIN}/news"],
            nested_sitemaps=[f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml"],
        )
        records, nested = parse_sitemap_xml(xml, "sitemap.xml")
        assert [r["url"] for r in records] == [f"{TEST_TARGET_DOMAIN}/news"]
        assert nested == [f"{TEST_TARGET_DOMAIN}/sitemap_posts.xml"]

    def test_raises_parse_error_on_malformed_xml(self):
        with pytest.raises(ET.ParseError):
            parse_sitemap_xml("<not valid", "bad.xml")

    def test_counts_exact_number_of_url_entries_in_one_document(self):
        """This is the base case the 'exact count' guarantee is built on:
        one sitemap document in, exact count of <url> entries out.
        """
        xml = make_sitemap_xml(urls=[f"{TEST_TARGET_DOMAIN}/page-{i}" for i in range(7)])
        records, _ = parse_sitemap_xml(xml, "sitemap.xml")
        assert len(records) == 7


class TestDedupeRecords:
    def test_removes_duplicate_urls_keeping_first_occurrence(self):
        records = [
            {"url": f"{TEST_TARGET_DOMAIN}/post-1", "source_sitemap": "sitemap_posts.xml"},
            {"url": f"{TEST_TARGET_DOMAIN}/news-1", "source_sitemap": "sitemap.xml"},
            {"url": f"{TEST_TARGET_DOMAIN}/post-1", "source_sitemap": "sitemap_calendar.xml"},  # dup
        ]
        result = dedupe_records(records)
        assert len(result) == 2
        assert {r["url"] for r in result} == {
            f"{TEST_TARGET_DOMAIN}/post-1",
            f"{TEST_TARGET_DOMAIN}/news-1",
        }
        # kept the FIRST occurrence's metadata, not the later duplicate's
        kept = next(r for r in result if r["url"] == f"{TEST_TARGET_DOMAIN}/post-1")
        assert kept["source_sitemap"] == "sitemap_posts.xml"

    def test_no_duplicates_returns_every_record_unchanged(self):
        records = [{"url": f"{TEST_TARGET_DOMAIN}/page-{i}"} for i in range(5)]
        assert len(dedupe_records(records)) == 5

    def test_all_duplicates_collapses_to_one(self):
        records = [{"url": f"{TEST_TARGET_DOMAIN}/same"} for _ in range(4)]
        assert len(dedupe_records(records)) == 1


class TestPartitionByRobots:
    def test_splits_allowed_and_disallowed(self):
        records = [
            {"url": f"{TEST_TARGET_DOMAIN}/news"},
            {"url": f"{TEST_TARGET_DOMAIN}/admin"},
        ]
        is_allowed = lambda url: "admin" not in url
        allowed, disallowed = partition_by_robots(records, is_allowed)
        assert [r["url"] for r in allowed] == [f"{TEST_TARGET_DOMAIN}/news"]
        assert [r["url"] for r in disallowed] == [f"{TEST_TARGET_DOMAIN}/admin"]
        assert disallowed[0]["status"] == "disallowed_by_robots"

    def test_every_input_record_ends_up_in_exactly_one_output_list(self):
        """Verifies no records are silently dropped during partitioning."""
        records = [{"url": f"{TEST_TARGET_DOMAIN}/page-{i}"} for i in range(10)]
        is_allowed = lambda url: int(url.split("-")[-1]) % 2 == 0  # even pages allowed
        allowed, disallowed = partition_by_robots(records, is_allowed)
        assert len(allowed) + len(disallowed) == len(records)


class TestAssignBucket:
    @pytest.mark.parametrize("url,expected_bucket", [
        (f"{TEST_TARGET_DOMAIN}/news", "/news/*"),
        (f"{TEST_TARGET_DOMAIN}/news/article-1", "/news/*"),
        (f"{TEST_TARGET_DOMAIN}/programs", "/programs/*"),
        (f"{TEST_TARGET_DOMAIN}/research/publications", "/research/*"),
        (f"{TEST_TARGET_DOMAIN}", "/"),
        (f"{TEST_TARGET_DOMAIN}/alumni", "/alumni/*"),  # never hardcoded anywhere, still works
    ])
    def test_bucket_classification_needs_no_prior_knowledge_of_site_structure(self, url, expected_bucket):
        assert assign_bucket(url) == expected_bucket


class TestBuildBucketSummary:
    def test_counts_exact_number_of_urls_per_bucket(self):
        records = [
            {"url": f"{TEST_TARGET_DOMAIN}/news", "source_sitemap": "sitemap.xml"},
            {"url": f"{TEST_TARGET_DOMAIN}/news/article-1", "source_sitemap": "sitemap_posts.xml"},
            {"url": f"{TEST_TARGET_DOMAIN}/news/article-2", "source_sitemap": "sitemap_posts.xml"},
            {"url": f"{TEST_TARGET_DOMAIN}/programs", "source_sitemap": "sitemap.xml"},
            {"url": f"{TEST_TARGET_DOMAIN}/campus", "source_sitemap": "sitemap.xml"},
        ]
        summary = build_bucket_summary(records)
        counts = {row["bucket"]: row["count"] for row in summary}
        assert counts == {
            "/news/*": 3,
            "/programs/*": 1,
            "/campus/*": 1,
        }

    def test_total_of_all_bucket_counts_equals_total_input_records(self):
        """Cross-check: bucketing must not gain or lose any records."""
        records = [{"url": f"{TEST_TARGET_DOMAIN}/section-{i % 4}/page-{i}", "source_sitemap": "s.xml"} for i in range(20)]
        summary = build_bucket_summary(records)
        assert sum(row["count"] for row in summary) == len(records)

    def test_mutates_records_in_place_with_bucket_key(self):
        records = [{"url": f"{TEST_TARGET_DOMAIN}/news", "source_sitemap": "sitemap.xml"}]
        build_bucket_summary(records)
        assert records[0]["bucket"] == "/news/*"
