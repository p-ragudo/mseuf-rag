"""
Query-time supersession of stale documents.

After reranking, near-identical candidates (same topic, different version) are
clustered. Inside a cluster, a candidate is dropped only when a sibling is
PROVABLY newer:
  * it covers a later academic period (AY 2026-2027 beats AY 2025-2026), or
  * same period (or both undated) and the sibling content was updated >1 day later.
Undated vs dated is never resolved by dropping: the LLM sees both with their
metadata and the QA prompt tells it which to prefer.

If the user asks about a specific period ("AY 2024-2025 tuition"), history is
what they want, so docs of that period are kept and other dated docs dropped.
Legacy points without `doc_period` in their payload are dated from their text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.services.query_pipeline.schema import SupersededInfo
from app.services.reranker.schema import RerankResult
from app.utils.temporal import extract_doc_period, format_period

NEAR_DUPLICATE_JACCARD = 0.90
SAME_HEADING_JACCARD = 0.60
SAME_URL_STEM_JACCARD = 0.50
UPDATE_GAP = timedelta(days=1)

_WORD_RE = re.compile(r"[a-z]{3,}")  # letters only: numbers/years/fees never affect similarity


@dataclass
class _Item:
    r: RerankResult
    period: Optional[int]
    updated: Optional[datetime]
    tokens: frozenset
    heading: str
    stem: str
    campus: str

    @property
    def url(self) -> str:
        return self.r.payload.get("source_url") or ""


def _parse_dt(value) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _norm_heading(h: str) -> str:
    return " ".join(w for w in re.sub(r"[^a-z]+", " ", (h or "").lower()).split() if len(w) > 2)


def _url_stem(url: str) -> str:
    return re.sub(r"\d+", "", urlparse(url).path.lower()).rstrip("/")


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _build(r: RerankResult) -> _Item:
    p = r.payload or {}
    period = p.get("doc_period")
    if not isinstance(period, int):
        period = extract_doc_period(
            r.content, url=p.get("source_url") or "", heading=p.get("heading_path") or ""
        )
    return _Item(
        r=r,
        period=period,
        updated=_parse_dt(p.get("page_updated_at")),
        tokens=frozenset(_WORD_RE.findall((r.content or "").lower())),
        heading=_norm_heading(p.get("heading_path") or ""),
        stem=_url_stem(p.get("source_url") or ""),
        campus=(p.get("campus") or "main"),
    )


def _same_topic(a: _Item, b: _Item) -> bool:
    if a.campus != b.campus:
        return False
    j = _jaccard(a.tokens, b.tokens)
    if j >= NEAR_DUPLICATE_JACCARD:
        return True
    if a.heading and a.heading == b.heading and j >= SAME_HEADING_JACCARD:
        return True
    if a.stem and a.stem == b.stem and j >= SAME_URL_STEM_JACCARD:
        return True
    return False


def _supersedes(w: _Item, m: _Item) -> Optional[str]:
    """Reason string if winner `w` provably makes `m` stale, else None."""
    if w.period is not None and m.period is not None:
        if w.period > m.period:
            return (
                f"newer academic period ({format_period(w.period)} vs {format_period(m.period)})"
            )
        if w.period < m.period:
            return None
    elif w.period is not None or m.period is not None:
        return None  # one side undated: not provable
    if w.updated and m.updated and (w.updated - m.updated) > UPDATE_GAP:
        return "same topic, more recently updated source"
    return None


def _clusters(items: List[_Item]) -> List[List[int]]:
    parent = list(range(len(items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _same_topic(items[i], items[j]):
                parent[find(i)] = find(j)

    groups: Dict[int, List[int]] = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def resolve_temporal_conflicts(
    query: str, results: List[RerankResult]
) -> Tuple[List[RerankResult], List[SupersededInfo]]:
    """Returns (kept results in original rerank order, telemetry about what was dropped)."""
    if len(results) < 2:
        return results, []

    items = [_build(r) for r in results]
    dropped_idx: Dict[int, Tuple[str, str]] = {}  # idx -> (reason, superseded_by_url)

    # 1) The user explicitly asked for a period: keep that period (and undated), drop other dated ones.
    q_period = extract_doc_period(query, allow_bare_year=True)
    if q_period is not None and any(it.period == q_period for it in items):
        for i, it in enumerate(items):
            if it.period is not None and it.period != q_period:
                dropped_idx[i] = (
                    f"query asks for {format_period(q_period)}, document covers {format_period(it.period)}",
                    "",
                )

    # 2) Supersession inside clusters of near-identical documents.
    alive = [i for i in range(len(items)) if i not in dropped_idx]
    sub = [items[i] for i in alive]
    for cluster in _clusters(sub):
        if len(cluster) < 2:
            continue
        ranked = sorted(
            cluster,
            key=lambda k: (
                sub[k].period if sub[k].period is not None else -1,
                sub[k].updated.timestamp() if sub[k].updated else 0.0,
                sub[k].r.rerank_score,
            ),
            reverse=True,
        )
        winner = sub[ranked[0]]
        for k in ranked[1:]:
            reason = _supersedes(winner, sub[k])
            if reason:
                dropped_idx[alive[k]] = (reason, winner.url)

    kept = [r for i, r in enumerate(results) if i not in dropped_idx]
    dropped = [
        SupersededInfo(
            source_url=items[i].url,
            heading_path=items[i].r.payload.get("heading_path") or "",
            reason=reason,
            superseded_by=by,
        )
        for i, (reason, by) in dropped_idx.items()
    ]
    return kept, dropped