import re

def clean_markdown(raw_markdown: str) -> str:
    """
    Cleans raw markdown by removing HTML tags, markdown links,
    image tags, and excessive blank lines while preserving headers.
    """
    if not raw_markdown:
        return ""

    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", raw_markdown)
    # Strip markdown links, preserving display text: [label](url) -> label
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Strip standalone image tags: ![]()
    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", text)
    # Collapse multiple consecutive blank lines to at most two
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse consecutive horizontal whitespace
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()