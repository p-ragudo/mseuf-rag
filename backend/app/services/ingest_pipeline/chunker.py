"""
Structure-aware markdown chunker (dependency-free, pure functions).

Why this exists
---------------
The old pipeline split markdown by header, then cut every section into
800-character windows with a 150-character overlap, and dropped any piece
under 15 words. For a procedure such as "Admission steps 1-8" that:

  * cut the list after ~3 items (an 800-char window holds very little),
  * discarded a short trailing piece such as "7. Pay fees  8. Get your ID",
  * left every piece after the first without its heading,
  * kept no ordering information, so nothing could ever fetch the rest.

This chunker keeps semantic units whole:

  1. Sections come from the heading hierarchy; each chunk carries its
     breadcrumb ("Admissions > Freshmen > Steps") as the first line.
  2. Lists, tables and code fences are atomic blocks. A lead-in line such as
     "Steps to apply:" is glued to the list that follows it, and a numbered
     list interrupted by a paragraph is re-joined (1-3 ... para ... 4-8).
  3. Small sibling sections are packed together up to ``target_chars``;
     tiny sections are merged into a neighbour instead of being dropped.
  4. A section is only split when it exceeds ``max_chars``. Splits happen at
     list-item / row / sentence boundaries, the lead-in (or table header) is
     repeated in every part, and parts are labelled "(part i of n)".
  5. Every chunk gets (chunk_index, section_id, part_index, part_total) so
     the query layer can reload the rest of a section or the neighbours.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+\u2022]|\d{1,3}[.)])\s+\S")
TOP_NUM_RE = re.compile(r"^(\d{1,3})[.)]\s+")
TABLE_RE = re.compile(r"^\s*\|")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}")
FENCE_RE = re.compile(r"^\s*(?:```|~~~)")

DEFAULT_TARGET_CHARS = 1500
DEFAULT_MAX_CHARS = 3200
DEFAULT_MIN_CHARS = 250

BOILERPLATE_INDICATORS = [
    "cookie", "privacy policy", "terms of use", "all rights reserved",
    "share on facebook", "share on x", "share on linkedin",
    "agree decline", "_chevron_right_", "navigation", "explore our website",
    "skip to content", "back to top", "read more", "click here",
    "related stories", "featured articles", "trending news", "leave a reply",
]


# --------------------------------------------------------------------------- #
# Shared helpers (re-exported by orchestrator for backward compatibility)
# --------------------------------------------------------------------------- #
def estimate_token_count(text: str) -> int:
    return max(1, len(text.split()))


def is_substantive_chunk(text: str, min_words: int = 8) -> bool:
    """Boilerplate filter. Applied to single-part chunks only (see chunk_markdown)."""
    words = text.split()
    if len(words) < min_words:
        return False

    lower_text = text.lower()
    matches = sum(1 for indicator in BOILERPLATE_INDICATORS if indicator in lower_text)
    if matches >= 2:
        return False

    symbols_count = len(re.findall(r"[_*\[\]\(\)!|#<>]", text))
    if symbols_count / max(1, len(text)) > 0.25:
        return False

    sentences = [s for s in re.split(r"[.!?\n]+", text) if len(s.strip().split()) >= 3]
    return len(sentences) >= 1


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #
@dataclass
class ChunkDraft:
    chunk_index: int       # 0-based reading order within the page
    section_id: str        # same for all parts of one section
    heading_path: str      # "A > B > C"
    part_index: int        # 1-based
    part_total: int
    content: str           # breadcrumb line + body (what is embedded / indexed / shown to the LLM)
    body: str              # body only


@dataclass
class _Block:
    kind: str              # para | list | table | code
    text: str
    lead_in: str = ""
    first_num: Optional[int] = None
    last_num: Optional[int] = None


@dataclass
class _Section:
    path: List[str]
    heading_line: str
    body: str


# --------------------------------------------------------------------------- #
# Block parsing
# --------------------------------------------------------------------------- #
def _numbers(text: str) -> List[int]:
    nums = []
    for line in text.split("\n"):
        m = TOP_NUM_RE.match(line)  # unindented numbered items only
        if m:
            nums.append(int(m.group(1)))
    return nums


def _parse_blocks(body: str) -> List[_Block]:
    lines = body.split("\n")
    n = len(lines)
    blocks: List[_Block] = []
    i = 0
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        if FENCE_RE.match(line):
            j = i + 1
            while j < n and not FENCE_RE.match(lines[j]):
                j += 1
            blocks.append(_Block("code", "\n".join(lines[i : j + 1])))
            i = j + 1
            continue

        if TABLE_RE.match(line):
            j = i
            while j < n and TABLE_RE.match(lines[j]):
                j += 1
            blocks.append(_Block("table", "\n".join(lines[i:j])))
            i = j
            continue

        if LIST_ITEM_RE.match(line):
            j = i + 1
            while j < n:
                nxt = lines[j]
                if not nxt.strip():
                    k = j + 1
                    while k < n and not lines[k].strip():
                        k += 1
                    if k < n and (LIST_ITEM_RE.match(lines[k]) or lines[k][:1] in (" ", "\t")):
                        j = k
                        continue
                    break
                if LIST_ITEM_RE.match(nxt) or nxt[:1] in (" ", "\t"):
                    j += 1
                    continue
                break
            text = "\n".join(lines[i:j]).rstrip()
            nums = _numbers(text)
            blocks.append(
                _Block("list", text, first_num=nums[0] if nums else None,
                       last_num=nums[-1] if nums else None)
            )
            i = j
            continue

        j = i + 1
        while (
            j < n
            and lines[j].strip()
            and not LIST_ITEM_RE.match(lines[j])
            and not TABLE_RE.match(lines[j])
            and not FENCE_RE.match(lines[j])
        ):
            j += 1
        blocks.append(_Block("para", "\n".join(lines[i:j])))
        i = j
    return blocks


def _glue_blocks(blocks: List[_Block]) -> List[_Block]:
    """Attach lead-ins to their list/table, and re-join interrupted numbered lists."""
    merged: List[_Block] = []
    k = 0
    while k < len(blocks):
        b = blocks[k]
        if (
            b.kind == "para"
            and k + 1 < len(blocks)
            and blocks[k + 1].kind in ("list", "table", "code")
            and b.text.rstrip().endswith(":")
            and len(b.text) <= 300
        ):
            nb = blocks[k + 1]
            lead = b.text.rstrip()
            merged.append(
                _Block(nb.kind, lead + "\n" + nb.text, lead_in=lead,
                       first_num=nb.first_num, last_num=nb.last_num)
            )
            k += 2
            continue
        merged.append(b)
        k += 1

    out: List[_Block] = []
    for b in merged:
        if b.kind == "list" and b.first_num and b.first_num > 1:
            joined = False
            for p in range(len(out) - 1, max(-1, len(out) - 5), -1):
                prev = out[p]
                if prev.kind == "list" and prev.last_num is not None and prev.last_num == b.first_num - 1:
                    combined = _Block(
                        "list",
                        "\n\n".join(x.text for x in out[p:] + [b]),
                        lead_in=prev.lead_in,
                        first_num=prev.first_num,
                        last_num=b.last_num,
                    )
                    del out[p:]
                    out.append(combined)
                    joined = True
                    break
            if joined:
                continue
        out.append(b)
    return out


# --------------------------------------------------------------------------- #
# Splitting oversized material (always at semantic boundaries)
# --------------------------------------------------------------------------- #
def _hard_split(text: str, limit: int) -> List[str]:
    parts: List[str] = []
    text = text.strip()
    while len(text) > limit:
        cut = text.rfind(" ", 0, limit)
        if cut < limit * 0.5:
            cut = limit
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _list_units(text: str) -> List[str]:
    units: List[str] = []
    cur: List[str] = []
    for line in text.split("\n"):
        if LIST_ITEM_RE.match(line) and not line[:1].isspace():
            if cur:
                units.append("\n".join(cur))
            cur = [line]
        else:
            cur.append(line)
    if cur:
        units.append("\n".join(cur))
    return units


def _pack_units(units: List[str], prefix: str, target: int, max_chars: int,
                min_chars: int, sep: str) -> List[str]:
    budget_max = max(200, max_chars - len(prefix) - 1)
    budget_target = max(200, target - len(prefix) - 1)

    flat: List[str] = []
    for u in units:
        flat.extend(_hard_split(u, budget_max) if len(u) > budget_max else [u])

    groups: List[List[str]] = []
    cur: List[str] = []
    cur_len = 0
    for u in flat:
        if cur and cur_len + len(u) + 1 > budget_target:
            groups.append(cur)
            cur, cur_len = [], 0
        cur.append(u)
        cur_len += len(u) + 1
    if cur:
        groups.append(cur)

    if len(groups) > 1:  # never leave a tiny orphan tail ("8. Get your ID")
        last = sum(len(u) + 1 for u in groups[-1])
        prev = sum(len(u) + 1 for u in groups[-2])
        if last < min_chars and prev + last <= budget_max:
            groups[-2].extend(groups[-1])
            groups.pop()

    return [(prefix + sep if prefix else "") + sep.join(g) for g in groups]


def _split_block(block: _Block, target: int, max_chars: int, min_chars: int) -> List[str]:
    text = block.text
    if len(text) <= max_chars:
        return [text]

    lead = block.lead_in
    body = text[len(lead):].lstrip("\n") if lead and text.startswith(lead) else text

    if block.kind == "list":
        return _pack_units(_list_units(body), lead, target, max_chars, min_chars, "\n")

    if block.kind == "table":
        rows = body.split("\n")
        header = rows[:2] if len(rows) >= 2 and TABLE_SEP_RE.match(rows[1]) else []
        units = rows[len(header):]
        prefix = "\n".join(([lead] if lead else []) + header)
        return _pack_units(units, prefix, target, max_chars, min_chars, "\n")

    if block.kind == "code":
        return _pack_units(body.split("\n"), lead, target, max_chars, min_chars, "\n")

    return _pack_units(_sentences(body) or [body], "", target, max_chars, min_chars, " ")


def _split_section_body(body: str, target: int, max_chars: int, min_chars: int) -> List[str]:
    if len(body) <= max_chars:
        return [body]

    parts: List[str] = []
    cur: List[str] = []
    cur_len = 0

    def flush() -> None:
        nonlocal cur, cur_len
        if cur:
            parts.append("\n\n".join(cur))
        cur, cur_len = [], 0

    for b in _glue_blocks(_parse_blocks(body)):
        if len(b.text) > max_chars:
            flush()
            parts.extend(_split_block(b, target, max_chars, min_chars))
            continue
        if cur and cur_len + len(b.text) + 2 > target:
            flush()
        cur.append(b.text)
        cur_len += len(b.text) + 2
    flush()

    if len(parts) > 1 and len(parts[-1]) < min_chars and len(parts[-2]) + len(parts[-1]) + 2 <= max_chars:
        parts[-2] = parts[-2] + "\n\n" + parts[-1]
        parts.pop()
    return parts


# --------------------------------------------------------------------------- #
# Sections and packing
# --------------------------------------------------------------------------- #
def _parse_sections(text: str) -> List[_Section]:
    sections: List[_Section] = []
    stack: List[tuple] = []
    cur_lines: List[str] = []
    cur_path: List[str] = []
    cur_head = ""
    in_fence = False

    def flush() -> None:
        body = "\n".join(cur_lines).strip()
        if body:
            sections.append(_Section(list(cur_path), cur_head, body))

    for line in text.split("\n"):
        if FENCE_RE.match(line):
            in_fence = not in_fence
        m = None if in_fence else HEADING_RE.match(line)
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2).strip().strip("#").strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            cur_path = [t for _, t in stack]
            cur_head = line.strip()
            cur_lines = []
        else:
            cur_lines.append(line)
    flush()
    return sections


def _section_text(s: _Section, with_heading: bool) -> str:
    return (s.heading_line + "\n" + s.body) if (with_heading and s.heading_line) else s.body


def _pack_len(pack: List[_Section]) -> int:
    multi = len(pack) > 1
    return sum(len(_section_text(s, multi)) + 2 for s in pack)


def _render_pack(pack: List[_Section]) -> str:
    multi = len(pack) > 1
    return "\n\n".join(_section_text(s, multi) for s in pack)


def _pack_path(pack: List[_Section]) -> List[str]:
    if len(pack) == 1:
        return pack[0].path
    common: List[str] = []
    for parts in zip(*[s.path for s in pack]):
        if all(p == parts[0] for p in parts):
            common.append(parts[0])
        else:
            break
    return common


def chunk_markdown(
    markdown: str,
    *,
    page_title: str = "",
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> List[ChunkDraft]:
    """Chunk already-cleaned markdown. See module docstring for the strategy."""
    text = (markdown or "").strip()
    if not text:
        return []

    sections = _parse_sections(text)
    if not sections:
        return []

    # Pass 1: pack consecutive siblings (same parent) up to target size.
    packs: List[List[_Section]] = []
    for s in sections:
        if (
            packs
            and packs[-1][0].path[:-1] == s.path[:-1]
            and _pack_len(packs[-1]) + len(s.body) + 2 <= target_chars
        ):
            packs[-1].append(s)
        else:
            packs.append([s])

    # Pass 2: merge tiny packs into a neighbour of the same top-level topic.
    merged: List[List[_Section]] = []
    for pack in packs:
        if (
            merged
            and merged[-1][0].path[:1] == pack[0].path[:1]
            and (_pack_len(pack) < min_chars or _pack_len(merged[-1]) < min_chars)
            and _pack_len(merged[-1]) + _pack_len(pack) <= max_chars
        ):
            merged[-1].extend(pack)
        else:
            merged.append(pack)

    drafts: List[ChunkDraft] = []
    for ordinal, pack in enumerate(merged):
        path = _pack_path(pack)
        heading_path = " > ".join(path)
        crumb = heading_path or page_title
        parts = _split_section_body(_render_pack(pack), target_chars, max_chars, min_chars)
        total = len(parts)
        section_id = hashlib.sha1(f"{ordinal}|{heading_path}".encode("utf-8")).hexdigest()[:16]

        for idx, part in enumerate(parts, start=1):
            part = part.strip()
            if not part:
                continue
            # Boilerplate filtering only for stand-alone chunks. A part of a
            # multi-part section is never dropped: that is how steps 7-8 got lost.
            if total == 1 and not is_substantive_chunk(part):
                continue
            header = f"Section: {crumb}" if crumb else ""
            if header and total > 1:
                header += f" (part {idx} of {total})"
            content = f"{header}\n\n{part}" if header else part
            drafts.append(
                ChunkDraft(
                    chunk_index=0,
                    section_id=section_id,
                    heading_path=heading_path,
                    part_index=idx,
                    part_total=total,
                    content=content,
                    body=part,
                )
            )

    for i, d in enumerate(drafts):  # contiguous reading order, gaps from dropped chunks removed
        d.chunk_index = i
    return drafts
