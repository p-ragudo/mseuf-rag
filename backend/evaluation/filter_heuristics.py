import re

BOILERPLATE_PATTERNS = [
    r"\ball rights reserved\b",
    r"\bclick here\b",
    r"\bread more\b",
    r"\bfollow us on\b",
    r"\bcookie policy\b",
    r"\bnavigation menu\b",
    r"\bprivacy policy\b",
    r"\bterms of use\b",
    r"\bshare via email\b",
    r"\bshare on\b",
    r"\bleave a reply\b",
    r"\bskip to content\b",
    r"\bback to top\b",
]

SUBSTANTIVE_INDICATORS = [
    "admission",
    "requirement",
    "requirements",
    "eligibility",
    "eligible",
    "deadline",
    "procedure",
    "procedures",
    "step",
    "steps",
    "fee",
    "fees",
    "tuition",
    "scholarship",
    "grading",
    "policy",
    "policies",
    "curriculum",
    "units",
    "schedule",
    "office",
    "department",
    "program",
    "prerequisite",
    "application",
    "enroll",
    "enrollment",
    "semester",
    "academic",
    "campus",
    "contact",
    "guideline",
    "guidelines",
    "document",
    "certificate",
]


def is_substantive_evaluation_chunk(
    text: str,
    heading_path: str = "",
    source_url: str = "",
    min_tokens: int = 45,
    max_tokens: int = 1600,
) -> bool:
    """
    Evaluates whether a chunk contains enough concrete, query-worthy information
    to serve as a ground-truth benchmark source for a tenant.
    """
    if not text or not text.strip():
        return False

    words = text.split()
    word_count = len(words)
    if word_count < min_tokens or word_count > max_tokens:
        return False

    combined_lower = f"{heading_path}\n{text}".lower()

    # 1. Filter out heavy markdown/symbol noise (e.g. broken ASCII tables or nav link dumps)
    symbols = len(re.findall(r"[_*\[\]\(\)!|#<>/\\-]", text))
    if symbols / max(1, len(text)) > 0.23:
        return False

    # 2. Check for boilerplate strings
    if any(re.search(pattern, combined_lower) for pattern in BOILERPLATE_PATTERNS):
        return False

    # 3. Exclude legal/utility headings
    if heading_path:
        ignored_headings = ("cookie", "privacy", "terms of use", "sitemap", "copyright")
        if any(h in heading_path.lower() for h in ignored_headings):
            return False

    # 4. Uploaded documents (document://) are curated files; accept if they pass length & noise checks
    if source_url.startswith("document://"):
        return True

    # 5. For scraped web pages, require numbers/dates/periods OR institutional domain keywords
    has_numeric_facts = bool(
        re.search(r"\b(?:\d{1,4}|a\.?y\.?\s*20\d{2}|20\d{2}\s*[-/]\s*20\d{2})\b", combined_lower)
    )
    has_domain_keywords = any(kw in combined_lower for kw in SUBSTANTIVE_INDICATORS)

    return has_numeric_facts or has_domain_keywords