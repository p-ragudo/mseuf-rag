"""
Shared test helpers: build fake sitemap XML and robots.txt content.

No real HTTP or disk access happens anywhere in this test suite - these builders
produce plain strings that stand in for what a real server would have returned.
"""


def make_sitemap_xml(urls: list[str] = None, nested_sitemaps: list[str] = None) -> str:
    """
    Builds fake sitemap XML with given page <url> entries and/or nested sitemap refs.
    """
    urls = urls or []
    nested = nested_sitemaps or []
    entries = "".join(f"<url><loc>{u}</loc><lastmod>2024-01-01</lastmod></url>" for u in urls)
    nested_entries = "".join(f"<url><loc>{s}</loc></url>" for s in nested)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{entries}{nested_entries}"
        "</urlset>"
    )


def make_robots_txt(sitemap_urls: list[str], disallow_paths: list[str] = None) -> str:
    """
    Builds fake robots.txt content.
    """
    lines = ["User-agent: *"]
    for path in (disallow_paths or []):
        lines.append(f"Disallow: {path}")
    lines.append("")
    for s in sitemap_urls:
        lines.append(f"Sitemap: {s}")
    return "\n".join(lines)
