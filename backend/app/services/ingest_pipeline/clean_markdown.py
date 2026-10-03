import re


def clean_markdown(raw_markdown: str) -> str:
    """
    Cleans raw markdown by removing HTML tags, markdown links,
    image tags, decorative separators, and sidebar/widget residue
    while strictly preserving markdown structural headings (#, ##, ###).
    """
    if not raw_markdown:
        return ""

    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", raw_markdown)

    # Strip markdown images: ![alt](url)
    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", text)

    # Strip markdown links, preserving label text: [label](url) -> label
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)

    # Strip raw markdown URLs left without brackets (http://... or https://...)
    text = re.sub(r"https?://\S+", "", text)

    # Strip horizontal rule noise lines (e.g. ---, ***, ___ on standalone lines)
    text = re.sub(r"^[ \t]*[-*_]{3,}[ \t]*$", "", text, flags=re.MULTILINE)

    # Strip social sharing and teaser breadcrumb residue
    text = re.sub(
        r"(?i)\b(share on facebook|share on x|share on twitter|share on linkedin|share via email)\b",
        "",
        text,
    )

    # Collapse multiple consecutive blank lines to at most two
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Collapse consecutive horizontal whitespace
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()