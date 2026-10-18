"""Academic-period and temporal helpers shared by ingestion and query time."""
import re
from collections import Counter
from datetime import date, datetime
from typing import Optional, Tuple
from urllib.parse import urlparse

# Standard academic periods: "AY 2025-2026", "A.Y. 2025-26", "SY2025/2026", "academic year 2025-2026"
_AY_RE = re.compile(
    r"(?:\ba\.?\s?y\.?|\bs\.?\s?y\.?|academic\s+year|school\s+year)\s*[:\-]?\s*"
    r"((?:19|20)\d{2})\s*[-\u2013\u2014/]\s*((?:19|20)?\d{2})(?!\d)",
    re.IGNORECASE,
)

# Term/Semester anchors: "1st Sem 2025-2026", "Term 2 2026"
_SEM_RE = re.compile(
    r"\b(?:1st|2nd|3rd|first|second|third|midyear|summer)?\s*(?:sem(?:ester)?|term|trimester)\s*"
    r"[:\-]?\s*(?:ay|sy)?\s*((?:19|20)\d{2})",
    re.IGNORECASE,
)

# Standard four-digit consecutive year ranges: "2025-2026"
_RANGE_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[-\u2013\u2014/]\s*((?:19|20)\d{2})(?!\d)")

# ISO Dates: "2026-08-15" or "2026/08/15"
_ISO_DATE_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})[-/](?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12]\d|3[01])(?!\d)")

# Bare Year: "2025" or "2026"
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


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
    Returns the target starting year of the academic or institutional period.
    Captures academic years, semesters, ISO document stamps, and URL structures.
    """
    hay = f"{heading}\n{text}"
    counts: Counter = Counter()

    # 1. Direct AY/SY notation (strongest signal: weight 4)
    for m in _AY_RE.finditer(hay):
        start = int(m.group(1))
        if _end_year(start, m.group(2)) == start + 1:
            counts[start] += 4

    # 2. Semester with year reference (weight 3)
    for m in _SEM_RE.finditer(hay):
        start = int(m.group(1))
        counts[start] += 3

    # 3. ISO format timestamps (weight 3)
    for m in _ISO_DATE_RE.finditer(hay):
        start = int(m.group(1))
        counts[start] += 3

    # 4. Standard year range "2025-2026" (weight 2)
    for m in _RANGE_RE.finditer(hay):
        start = int(m.group(1))
        if int(m.group(2)) == start + 1:
            counts[start] += 2

    # 5. URL path patterns: /2025/ or /ay-2025-2026/ (weight 2)
    path = urlparse(url).path if url else ""
    for m in _YEAR_RE.finditer(path):
        counts[int(m.group(1))] += 2

    # 6. Bare year extraction for user queries (e.g., "admissions 2026")
    if allow_bare_year:
        for m in _YEAR_RE.finditer(hay):
            counts[int(m.group(1))] += 1

    if not counts:
        return None

    top_count = max(counts.values())
    return max(year for year, count in counts.items() if count == top_count)


def current_academic_year_start(today: Optional[date] = None) -> int:
    """Calculates active academic anchor safely without regional month bias."""
    today = today or date.today()
    # If past Q1, current year is typically the active starting academic cycle
    return today.year if today.month >= 5 else today.year - 1


def format_period(start_year: Optional[int]) -> Optional[str]:
    return f"{start_year}-{start_year + 1}" if isinstance(start_year, int) else None