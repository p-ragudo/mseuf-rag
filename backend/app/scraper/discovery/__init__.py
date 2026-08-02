"""
Sitemap discovery pipeline.

Three files:
    config.py    - paths, constants, env
    logic.py     - all pure functions: parsing, dedupe, filtering, bucketing
    pipeline.py  - all I/O + orchestration: fetch, save, crawl, run_discovery
"""

from .pipeline import run_discovery

__all__ = ["run_discovery"]
