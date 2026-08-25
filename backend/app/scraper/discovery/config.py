"""
Config: paths, constants, and environment-derived settings.
"""

from pathlib import Path
from app.core.config import settings

# app/scraper/discovery/config.py -> parents[3] reaches backend/
BASE_DIR = Path(__file__).resolve().parents[3]
DISCOVERY_DIR = BASE_DIR / "data" / "discovery"
RAW_SITEMAP_DIR = DISCOVERY_DIR / "raw_sitemaps"

DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
RAW_SITEMAP_DIR.mkdir(parents=True, exist_ok=True)

TARGET_DOMAIN = settings.target_domain

if not TARGET_DOMAIN:
    raise ValueError(
        "[!] TARGET_DOMAIN environment variable is not set in .env file."
    )

ROBOTS_URL = f"{TARGET_DOMAIN}/robots.txt" if TARGET_DOMAIN else None
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
