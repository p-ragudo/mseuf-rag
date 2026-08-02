"""
Config: paths, constants, and environment-derived settings.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# app/scraper/discovery/config.py -> parents[3] reaches backend/
BASE_DIR = Path(__file__).resolve().parents[3]
DISCOVERY_DIR = BASE_DIR / "data" / "discovery"
RAW_SITEMAP_DIR = DISCOVERY_DIR / "raw_sitemaps"

DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
RAW_SITEMAP_DIR.mkdir(parents=True, exist_ok=True)

TARGET_DOMAIN = os.getenv("TARGET_DOMAIN")

if not TARGET_DOMAIN:
    raise ValueError(
        "[!] TARGET_DOMAIN environment variable is not set in .env file."
    )

ROBOTS_URL = f"{TARGET_DOMAIN}/robots.txt" if TARGET_DOMAIN else None
USER_AGENT = "ThesisScraperBot/1.0"
