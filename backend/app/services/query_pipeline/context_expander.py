"""
Query-time "small-to-big" expansion.

Retrieval finds the best chunk, but a chunk can be one part of a longer
procedure (steps 1-3 of 8). Before the LLM sees the context we reload the
rest from PostgreSQL (the source of truth):

  * every part of the same section (section_id)  -> a procedure is never partial
  * +/- ``window`` neighbouring chunks of the top ``expand_top_n`` hits
    -> covers "continued below" content that landed in the next section

Contiguous chunks of a page are merged into ONE context item in reading
order. Tenant isolation is enforced again in SQL (ScrapedPage.org_id).
Hits whose chunk no longer exists in Postgres (orphaned Qdrant points) or
legacy chunks without chunk_index fall back to the payload text.
"""
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import and_, or_, select

from app.core.database import async_session
from app.models.chunk import Chunk
from app.models.scraped_page import ScrapedPage
from app.services.llm_qa.schema import MatchedQuestionDetail, RetrievedContextItem
from app.services.reranker.schema import RerankResult


def _slug_title(url: str) -> str:
    return url.rstrip("/").split("/")[-1] or "Document"


class ContextExpander:
    def __init__(self, window: int = 1, expand_top_n: int = 3, max_chars: int = 16000):
        self.window = window
        self.expand_top_n = expand_top_n
        self.max_chars = max_chars

    async def expand(
        self, org_id: int, results: Sequence[RerankResult]
    ) -> List[RetrievedContextItem]:
        if not results:
            return []

        hit_ids: List[Optional[int]] = []
        for r in results:
            try:
                hit_ids.append(int(r.payload.get("chunk_id")))
            except (TypeError, ValueError):
                hit_ids.append(None)

        valid_ids = [i for i in hit_ids if i is not None]
        hit_rows: Dict[int, Chunk] = {}
        chunks_by_page: Dict[int, Dict[int, Chunk]] = {}
        url_by_page: Dict[int, str] = {}

        if valid_ids:
            async with async_session() as session:
                res = await session.execute(
                    select(Chunk, ScrapedPage.url)
                    .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
                    .where(Chunk.id.in_(valid_ids), ScrapedPage.org_id == org_id)
                )
                for chunk, url in res.all():
                    hit_rows[chunk.id] = chunk
                    url_by_page[chunk.page_id] = url

                wanted_sections: Dict[int, Set[str]] = {}
                wanted_indices: Dict[int, Set[int]] = {}
                for rank, cid in enumerate(hit_ids):
                    ch = hit_rows.get(cid) if cid is not None else None
                    if ch is None or ch.chunk_index is None:
                        continue
                    wanted_indices.setdefault(ch.page_id, set()).add(ch.chunk_index)
                    if ch.section_id:
                        wanted_sections.setdefault(ch.page_id, set()).add(ch.section_id)
                    if rank < self.expand_top_n:
                        for d in range(-self.window, self.window + 1):
                            if ch.chunk_index + d >= 0:
                                wanted_indices[ch.page_id].add(ch.chunk_index + d)

                conds = []
                for page_id, idxs in wanted_indices.items():
                    inner = [Chunk.chunk_index.in_(sorted(idxs))]
                    if wanted_sections.get(page_id):
                        inner.append(Chunk.section_id.in_(sorted(wanted_sections[page_id])))
                    conds.append(and_(Chunk.page_id == page_id, or_(*inner)))

                if conds:
                    res = await session.execute(
                        select(Chunk, ScrapedPage.url)
                        .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
                        .where(ScrapedPage.org_id == org_id, or_(*conds))
                    )
                    for ch, url in res.all():
                        if ch.chunk_index is None:
                            continue
                        chunks_by_page.setdefault(ch.page_id, {})[ch.chunk_index] = ch
                        url_by_page[ch.page_id] = url

        # (best_rank, item)
        entries: List[Tuple[int, RetrievedContextItem]] = []

        # Per page: contiguous runs in reading order.
        hit_info: Dict[Tuple[int, int], int] = {}  # (page_id, chunk_index) -> best hit rank
        for rank, cid in enumerate(hit_ids):
            ch = hit_rows.get(cid) if cid is not None else None
            if ch is not None and ch.chunk_index is not None:
                hit_info.setdefault((ch.page_id, ch.chunk_index), rank)

        for page_id, by_index in chunks_by_page.items():
            indices = sorted(by_index)
            runs: List[List[int]] = []
            for i in indices:
                if runs and i == runs[-1][-1] + 1:
                    runs[-1].append(i)
                else:
                    runs.append([i])

            for run in runs:
                ranks = [hit_info[(page_id, i)] for i in run if (page_id, i) in hit_info]
                if not ranks:
                    continue  # run made only of expansion extras that no hit anchors
                best_rank = min(ranks)
                anchor = results[best_rank]
                matched: List[MatchedQuestionDetail] = []
                seen_q: Set[str] = set()
                for rk in ranks:
                    for mq in results[rk].matched_questions:
                        if mq.question not in seen_q:
                            seen_q.add(mq.question)
                            matched.append(mq)

                first_chunk = by_index[run[0]]
                entries.append(
                    (
                        best_rank,
                        RetrievedContextItem(
                            title=first_chunk.heading_path or _slug_title(url_by_page[page_id]),
                            content="\n\n".join(by_index[i].content for i in run),
                            source_url=url_by_page[page_id],
                            campus=anchor.payload.get("campus") or "main",
                            academic_level=anchor.payload.get("academic_level") or "general",
                            initial_score=max(results[rk].initial_score for rk in ranks),
                            rerank_score=max(results[rk].rerank_score for rk in ranks),
                            matched_questions=matched,
                        ),
                    )
                )

        # Hits that could not be resolved in Postgres: use the payload text.
        for rank, (r, cid) in enumerate(zip(results, hit_ids)):
            ch = hit_rows.get(cid) if cid is not None else None
            if ch is not None and ch.chunk_index is not None:
                continue
            url = r.payload.get("source_url") or ""
            entries.append(
                (
                    rank,
                    RetrievedContextItem(
                        title=r.payload.get("heading_path") or _slug_title(url),
                        content=r.content,
                        source_url=url,
                        campus=r.payload.get("campus") or "main",
                        academic_level=r.payload.get("academic_level") or "general",
                        initial_score=r.initial_score,
                        rerank_score=r.rerank_score,
                        matched_questions=r.matched_questions,
                    ),
                )
            )

        entries.sort(key=lambda e: e[0])

        out: List[RetrievedContextItem] = []
        used = 0
        for best_rank, item in entries:
            if out and best_rank > 0 and used + len(item.content) > self.max_chars:
                continue  # budget: the top hit is always kept in full
            out.append(item)
            used += len(item.content)
        return out
