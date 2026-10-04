import re

_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.DOTALL)


def clean_markdown(raw_markdown: str) -> str:
    """
    Cleans raw crawler markdown while preserving the structure the chunker needs:
    headings, list markers, list indentation (nested items), numbering and tables.

    Changes vs the old version:
      * YAML frontmatter is stripped FIRST (it used to be dead code, because the
        '---' rule below removed the delimiters before the check ran).
      * Leading indentation is preserved (the old `[ \\t]+ -> ' '` flattened
        nested lists and indented continuation lines).
      * Escaped numbering such as '3\\.' is restored to '3.' so numbered steps
        are recognised as one list.
      * HTML tag stripping only matches real tags, so "< 5 units > 2" survives.
    """
    if not raw_markdown:
        return ""

    text = raw_markdown.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")

    text = _FRONTMATTER_RE.sub("", text, count=1)

    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"</?[a-zA-Z][^>]*>", " ", text)

    text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)

    # Horizontal rules (standalone ---, ***, ___). Table separator rows contain '|' so they are safe.
    text = re.sub(r"^[ \t]*[-*_]{3,}[ \t]*$", "", text, flags=re.MULTILINE)

    text = re.sub(
        r"(?i)\b(share on facebook|share on x|share on twitter|share on linkedin|share via email)\b",
        "",
        text,
    )

    # Restore escaped ordered-list markers: "3\." -> "3."
    text = re.sub(r"^(\s*\d{1,3})\\([.)])", r"\1\2", text, flags=re.MULTILINE)

    # Trim trailing whitespace per line and collapse inner runs of spaces,
    # but never touch leading indentation.
    cleaned_lines = []
    for line in text.split("\n"):
        stripped = line.rstrip()
        indent_len = len(stripped) - len(stripped.lstrip(" \t"))
        indent, rest = stripped[:indent_len], stripped[indent_len:]
        rest = re.sub(r"[ \t]{2,}", " ", rest)
        cleaned_lines.append(indent + rest if rest else "")
    text = "\n".join(cleaned_lines)

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
