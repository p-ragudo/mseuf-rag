import re

BOILERPLATE_PATTERNS = [
    r"\ball rights reserved\b", r"\bclick here\b", r"\bread more\b", r"\bfollow us on\b", r"\bcookie policy\b",
    r"\bnavigation menu\b", r"\bprivacy policy\b", r"\bterms of use\b", r"\bshare via email\b", r"\bshare on\b",
    r"\bleave a reply\b", r"\bskip to content\b", r"\bback to top\b",
]

SUBSTANTIVE_INDICATORS = [
    "admission", "requirement", "requirements", "eligibility", "eligible", "deadline", "procedure", "procedures",
    "step", "steps", "fee", "fees", "tuition", "scholarship", "grading", "policy", "policies", "curriculum", "units",
    "schedule", "office", "department", "program", "prerequisite", "application", "enroll", "enrollment", "semester",
    "academic", "campus", "contact", "guideline", "guidelines", "document", "certificate",
]


def is_substantive_evaluation_chunk(
    text: str,
    heading_path: str = "",
    source_url: str = "",
    min_tokens: int = 45,
    max_tokens: int = 1600,
) -> bool:
    """Is this chunk concrete enough to be a benchmark source?"""
    if not text or not text.strip():
        return False

    word_count = len(text.split())
    if word_count < min_tokens or word_count > max_tokens:
        return False

    combined_lower = f"{heading_path}\n{text}".lower()

    symbols = len(re.findall(r"[_*\[\]\(\)!|#<>/\\-]", text))
    if symbols / max(1, len(text)) > 0.23:
        return False

    if any(re.search(p, combined_lower) for p in BOILERPLATE_PATTERNS):
        return False

    if heading_path:
        ignored = ("cookie", "privacy", "terms of use", "sitemap", "copyright")
        if any(h in heading_path.lower() for h in ignored):
            return False

    if source_url.startswith("document://"):
        return True

    # Needs real numeric facts (>= 2 numbers of 2+ digits, or an academic-year pattern) OR domain keywords.
    # (The old rule accepted any single digit, so almost every page passed.)
    has_numeric_facts = (
        len(re.findall(r"\b\d{2,4}\b", combined_lower)) >= 2
        or bool(re.search(r"\ba\.?y\.?\s*20\d{2}|20\d{2}\s*[-\u2013/]\s*20\d{2}", combined_lower))
    )
    has_domain_keywords = any(re.search(rf"\b{re.escape(kw)}\b", combined_lower) for kw in SUBSTANTIVE_INDICATORS)
    return has_numeric_facts or has_domain_keywords
