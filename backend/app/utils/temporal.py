"""Academic-period helpers shared by ingestion and query time."""
import re
from collections import Counter
from datetime import date
from typing import Optional
from urllib.parse import urlparse

# "AY 2025-2026", "A.Y. 2025-26", "SY2025/2026", "academic year 2025-2026"
_AY_RE = re.compile(
    r"(?:\ba\.?\s?y\.?|\bs\.?\s?y\.?|academic\s+year|school\s+year)\s*[:\-]?\s*"
    r"((?:19|20)\d{2})\s*[-\u2013\u2014/]\s*((?:19|20)?\d{2})(?!\d)",
    re.IGNORECASE,
)
# bare consecutive-year range "2025-2026"
_RANGE_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[-\u2013\u2014/]\s*((?:19|20)\d{2})(?!\d)")
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def _end_year(start: int, raw: str) -> int:
    end = int(raw)
    if end < 100:
        end += (start // 100) * 100
    return end


def extract_doc_period(
    text: str,
    *,
    url: str = "",
    heading: str = "",
    allow_bare_year: bool = False,
) -> Optional[int]:
    """
    Returns the START year of the academic period a text is about (2025 for AY 2025-2026),
    or None when no signal exists. Most frequent signal wins, ties go to the later year.
    `allow_bare_year` is meant for user queries ("tuition 2025").
    """
    hay = f"{heading}\n{text}"
    counts: Counter = Counter()

    for m in _AY_RE.finditer(hay):
        start = int(m.group(1))
        if _end_year(start, m.group(2)) == start + 1:
            counts[start] += 3
    for m in _RANGE_RE.finditer(hay):
        start = int(m.group(1))
        if int(m.group(2)) == start + 1:
            counts[start] += 1

    path = urlparse(url).path if url else ""
    for m in _YEAR_RE.finditer(path):
        counts[int(m.group(1))] += 2

    if allow_bare_year:
        for m in _YEAR_RE.finditer(hay):
            counts[int(m.group(1))] += 1

    if not counts:
        return None
    top = max(counts.values())
    return max(year for year, c in counts.items() if c == top)


def current_academic_year_start(today: Optional[date] = None, start_month: int = 6) -> int:
    today = today or date.today()
    return today.year if today.month >= start_month else today.year - 1


def format_period(start_year: Optional[int]) -> Optional[str]:
    return f"{start_year}-{start_year + 1}" if isinstance(start_year, int) else None