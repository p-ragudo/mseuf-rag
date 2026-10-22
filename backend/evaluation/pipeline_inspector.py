"""Runs the PRODUCTION retrieval path step by step and records every stage.

This mirrors QueryPipeline.execute() for a single-turn question with the cache bypassed. It calls the pipeline's own
_hybrid_search / _reciprocal_rank_fusion / reranker / resolve_temporal_conflicts / expander / qa_synthesizer, so
changes to those components are picked up automatically. `run_evaluation.py --parity-check N` re-verifies that this
copy still returns the same contexts as QueryPipeline.execute().
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.services.llm_qa.schema import QARequest, RetrievedContextItem
from app.services.query_pipeline.query_pipeline import QueryPipeline, _normalize_campus
from app.services.query_pipeline.temporal_resolver import resolve_temporal_conflicts
from app.services.reranker.schema import RerankCandidate


@dataclass
class StageCandidate:
    rank: int  # 1-based
    parent_chunk_uuid: str
    sql_chunk_id: Optional[int]
    source_url: str
    score: float
    content: str


@dataclass
class InstrumentedQueryResult:
    query: str
    org_id: int
    answer: str = ""
    source: str = "llm"  # "llm" | "fallback" | "retrieval_only"
    sources: List[str] = field(default_factory=list)
    detected_campus: Optional[str] = None
    fallback_reason: Optional[str] = None  # no_candidates | reranker_empty | no_contexts
    latency_ms: float = 0.0
    retrieval_latency_ms: float = 0.0
    # Stage A/B: unique chunk ids in the order each retriever returned them (question points collapsed to chunks)
    dense_chunk_order: List[int] = field(default_factory=list)
    sparse_chunk_order: List[int] = field(default_factory=list)
    # Stage C: after RRF, the pool handed to the reranker
    pre_rerank_candidates: List[StageCandidate] = field(default_factory=list)
    # Stage D: after cross-encoder only (this isolates the reranker)
    post_rerank_candidates: List[StageCandidate] = field(default_factory=list)
    # Stage E: after score-threshold + temporal resolution + top_k (what production actually keeps)
    final_reranked_candidates: List[StageCandidate] = field(default_factory=list)
    # Stage F: after Postgres small-to-big expansion (what the answer LLM reads)
    expanded_contexts: List[RetrievedContextItem] = field(default_factory=list)


def _extract_sql_chunk_id(payload: dict) -> Optional[int]:
    val = (payload or {}).get("chunk_id")
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _ordered_unique_chunk_ids(hits: list) -> List[int]:
    seen = set()
    out: List[int] = []
    for h in hits:
        cid = _extract_sql_chunk_id(getattr(h, "payload", {}) or {})
        if cid is None or cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


async def execute_instrumented_query(
    pipeline: QueryPipeline,
    org_id: int,
    query: str,
    top_k: int = 5,
    generate_answer: bool = True,
) -> InstrumentedQueryResult:
    t0 = time.perf_counter()
    res = InstrumentedQueryResult(query=query, org_id=org_id)

    chosen_top_k = top_k or settings.default_top_k
    resolved_top_k = max(settings.min_top_k, min(chosen_top_k, settings.max_top_k))

    def _finish(source: Optional[str] = None, answer: Optional[str] = None, reason: Optional[str] = None):
        if source is not None:
            res.source = source
        if answer is not None:
            res.answer = answer
        if reason is not None:
            res.fallback_reason = reason
        res.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return res

    # 1. Dense query vector + org details (read-only)
    dense_embed, (org_name, known_locations, _version) = await asyncio.gather(
        pipeline.embedder.embed_one(query, task_type="RETRIEVAL_QUERY"),
        pipeline._resolve_org_details(org_id),
    )
    dense_vec = dense_embed.values

    # 2. Intent classification + sparse BM25 query encoding
    intent, sparse_data = await asyncio.gather(
        pipeline.classifier.classify_intent(query, org_name=org_name, known_locations=known_locations),
        pipeline.sparse_embedder.embed_query(query),
    )
    campus = _normalize_campus(intent.detected_sub_entity)
    res.detected_campus = campus

    # 3. Hybrid retrieval
    tenant_filter: Dict[str, str] = {"group_id": str(org_id)}
    if campus:
        tenant_filter["campus"] = campus

    candidate_limit = max(resolved_top_k * 6, 30)
    dense_hits, sparse_hits = await pipeline._hybrid_search(dense_vec, sparse_data, tenant_filter, candidate_limit)
    if not dense_hits and not sparse_hits and campus:
        dense_hits, sparse_hits = await pipeline._hybrid_search(
            dense_vec, sparse_data, {"group_id": str(org_id)}, candidate_limit
        )

    res.dense_chunk_order = _ordered_unique_chunk_ids(dense_hits)
    res.sparse_chunk_order = _ordered_unique_chunk_ids(sparse_hits)

    # 4. RRF fusion
    fused = pipeline._reciprocal_rank_fusion(dense_hits, sparse_hits, k=60)
    if not fused:
        res.retrieval_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return _finish("fallback", "No relevant institutional documents could be found for your query.", "no_candidates")

    rerank_pool_size = max(resolved_top_k * 4, 25)
    rerank_inputs: List[RerankCandidate] = []
    for idx, (pid, rrf_score, payload, mqs) in enumerate(fused[:rerank_pool_size], start=1):
        c_text = (payload.get("chunk_text") or "").strip()
        if not c_text:
            continue
        res.pre_rerank_candidates.append(
            StageCandidate(
                rank=len(res.pre_rerank_candidates) + 1,
                parent_chunk_uuid=str(pid),
                sql_chunk_id=_extract_sql_chunk_id(payload),
                source_url=payload.get("source_url") or "",
                score=float(rrf_score),
                content=c_text,
            )
        )
        rerank_inputs.append(
            RerankCandidate(chunk_id=str(pid), content=c_text, initial_score=float(rrf_score),
                            payload=payload, matched_questions=mqs)
        )

    # 5. Cross-encoder
    reranked = await pipeline.reranker.rerank(
        query=query,
        candidates=rerank_inputs,
        top_k=resolved_top_k * 2,
        score_threshold=settings.reranker_score_threshold,
    )
    res.post_rerank_candidates = [
        StageCandidate(
            rank=i,
            parent_chunk_uuid=str(r.chunk_id),
            sql_chunk_id=_extract_sql_chunk_id(r.payload),
            source_url=r.payload.get("source_url") or "",
            score=float(r.rerank_score),
            content=r.content,
        )
        for i, r in enumerate(reranked, start=1)
    ]
    if not reranked:
        res.retrieval_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return _finish("fallback", "No sufficiently relevant institutional information was found to answer your inquiry.",
                       "reranker_empty")

    # 6. Temporal conflict resolution + top_k
    temporally_resolved, _superseded = resolve_temporal_conflicts(query, reranked)
    top_reranked = temporally_resolved[:resolved_top_k]
    res.final_reranked_candidates = [
        StageCandidate(
            rank=i,
            parent_chunk_uuid=str(r.chunk_id),
            sql_chunk_id=_extract_sql_chunk_id(r.payload),
            source_url=r.payload.get("source_url") or "",
            score=float(r.rerank_score),
            content=r.content,
        )
        for i, r in enumerate(top_reranked, start=1)
    ]

    # 7. Small-to-big expansion (Postgres read)
    contexts = await pipeline.expander.expand(org_id, top_reranked)
    res.expanded_contexts = list(contexts or [])
    res.retrieval_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    if not contexts:
        return _finish("fallback", "No sufficiently relevant institutional information was found to answer your inquiry.",
                       "no_contexts")

    if not generate_answer:
        return _finish("retrieval_only", "")

    # 8. Grounded answer synthesis
    qa_response = await pipeline.qa_synthesizer.generate_answer(QARequest(query=query, contexts=contexts), org_name=org_name)
    final_answer = qa_response.answer
    if intent.is_ambiguous and intent.clarification_message:
        final_answer += f"\n\n---\n*Note*: {intent.clarification_message}"
    res.sources = qa_response.sources
    return _finish("llm", final_answer)
