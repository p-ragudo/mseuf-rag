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
    rank: int  # 1-based rank
    parent_chunk_uuid: str
    sql_chunk_id: Optional[int]
    source_url: str
    score: float
    content: str


@dataclass
class InstrumentedQueryResult:
    query: str
    org_id: int
    answer: str
    source: str  # "llm" | "fallback" | "cache"
    sources: List[str]
    detected_campus: Optional[str]
    latency_ms: float
    # Stage 5: Post-RRF (Before Cross-Encoder)
    pre_rerank_candidates: List[StageCandidate] = field(default_factory=list)
    # Stage 6: Post-Cross-Encoder (Before Temporal Drop)
    post_rerank_candidates: List[StageCandidate] = field(default_factory=list)
    # Stage 7: Post-Temporal Resolution Top-K
    final_reranked_candidates: List[StageCandidate] = field(default_factory=list)
    # Stage 8: Post-SQL Small-to-Big Context Expansion
    expanded_contexts: List[RetrievedContextItem] = field(default_factory=list)


def _extract_sql_chunk_id(payload: dict) -> Optional[int]:
    val = payload.get("chunk_id")
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


async def execute_instrumented_query(
    pipeline: QueryPipeline,
    org_id: int,
    query: str,
    top_k: int = 5,
) -> InstrumentedQueryResult:
    """
    Executes the exact production QueryPipeline steps while capturing intermediate
    RRF (pre-rerank) and Cross-Encoder (post-rerank) candidate lists for ablation & lift metrics.
    """
    t0 = time.perf_counter()
    chosen_top_k = top_k or settings.default_top_k
    resolved_top_k = max(settings.min_top_k, min(chosen_top_k, settings.max_top_k))

    # 1. Embed query + Resolve Org Details + Classify Intent + Sparse BM25 in parallel
    dense_embed, (org_name, known_locations, _version) = await asyncio.gather(
        pipeline.embedder.embed_one(query, task_type="RETRIEVAL_QUERY"),
        pipeline._resolve_org_details(org_id),
    )
    dense_vec = dense_embed.values

    intent, sparse_data = await asyncio.gather(
        pipeline.classifier.classify_intent(
            query, org_name=org_name, known_locations=known_locations
        ),
        pipeline.sparse_embedder.embed_query(query),
    )
    campus = _normalize_campus(intent.detected_sub_entity)

    # 2. Hybrid Retrieval in Qdrant
    tenant_filter: Dict[str, str] = {"group_id": str(org_id)}
    if campus:
        tenant_filter["campus"] = campus

    candidate_limit = max(resolved_top_k * 6, 30)
    dense_hits, sparse_hits = await pipeline._hybrid_search(
        dense_vec, sparse_data, tenant_filter, candidate_limit
    )

    if not dense_hits and not sparse_hits and campus:
        dense_hits, sparse_hits = await pipeline._hybrid_search(
            dense_vec, sparse_data, {"group_id": str(org_id)}, candidate_limit
        )

    # 3. Reciprocal Rank Fusion (RRF) — BEFORE CROSS-ENCODER
    fused = pipeline._reciprocal_rank_fusion(dense_hits, sparse_hits, k=60)
    if not fused:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return InstrumentedQueryResult(
            query=query,
            org_id=org_id,
            answer="No relevant institutional documents could be found for your query.",
            source="fallback",
            sources=[],
            detected_campus=campus,
            latency_ms=latency_ms,
        )

    rerank_pool_size = max(resolved_top_k * 4, 25)
    pre_rerank_slice = fused[:rerank_pool_size]

    pre_rerank_candidates: List[StageCandidate] = []
    rerank_inputs: List[RerankCandidate] = []

    for idx, (pid, rrf_score, payload, mqs) in enumerate(pre_rerank_slice, start=1):
        c_text = (payload.get("chunk_text") or "").strip()
        if not c_text:
            continue
        sql_cid = _extract_sql_chunk_id(payload)
        s_url = payload.get("source_url") or ""

        pre_rerank_candidates.append(
            StageCandidate(
                rank=idx,
                parent_chunk_uuid=str(pid),
                sql_chunk_id=sql_cid,
                source_url=s_url,
                score=float(rrf_score),
                content=c_text,
            )
        )
        rerank_inputs.append(
            RerankCandidate(
                chunk_id=str(pid),
                content=c_text,
                initial_score=float(rrf_score),
                payload=payload,
                matched_questions=mqs,
            )
        )

    # 4. Cross-Encoder Reranking — AFTER CROSS-ENCODER
    reranked = await pipeline.reranker.rerank(
        query=query,
        candidates=rerank_inputs,
        top_k=resolved_top_k * 2,
        score_threshold=settings.reranker_score_threshold,
    )

    post_rerank_candidates: List[StageCandidate] = [
        StageCandidate(
            rank=idx,
            parent_chunk_uuid=str(r.chunk_id),
            sql_chunk_id=_extract_sql_chunk_id(r.payload),
            source_url=r.payload.get("source_url") or "",
            score=float(r.rerank_score),
            content=r.content,
        )
        for idx, r in enumerate(reranked, start=1)
    ]

    if not reranked:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return InstrumentedQueryResult(
            query=query,
            org_id=org_id,
            answer="No sufficiently relevant institutional information was found to answer your inquiry.",
            source="fallback",
            sources=[],
            detected_campus=campus,
            latency_ms=latency_ms,
            pre_rerank_candidates=pre_rerank_candidates,
        )

    # 5. Temporal Conflict Resolution
    temporally_resolved, _superseded = resolve_temporal_conflicts(query, reranked)
    top_reranked = temporally_resolved[:resolved_top_k]

    final_reranked_candidates: List[StageCandidate] = [
        StageCandidate(
            rank=idx,
            parent_chunk_uuid=str(r.chunk_id),
            sql_chunk_id=_extract_sql_chunk_id(r.payload),
            source_url=r.payload.get("source_url") or "",
            score=float(r.rerank_score),
            content=r.content,
        )
        for idx, r in enumerate(top_reranked, start=1)
    ]

    # 6. Small-to-Big SQL Context Expansion
    contexts = await pipeline.expander.expand(org_id, top_reranked)
    if not contexts:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return InstrumentedQueryResult(
            query=query,
            org_id=org_id,
            answer="No sufficiently relevant institutional information was found to answer your inquiry.",
            source="fallback",
            sources=[],
            detected_campus=campus,
            latency_ms=latency_ms,
            pre_rerank_candidates=pre_rerank_candidates,
            post_rerank_candidates=post_rerank_candidates,
            final_reranked_candidates=final_reranked_candidates,
        )

    # 7. Grounded LLM Answer Synthesis
    qa_response = await pipeline.qa_synthesizer.generate_answer(
        QARequest(query=query, contexts=contexts), org_name=org_name
    )
    final_answer = qa_response.answer
    if intent.is_ambiguous and intent.clarification_message:
        final_answer += f"\n\n---\n*Note*: {intent.clarification_message}"

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    return InstrumentedQueryResult(
        query=query,
        org_id=org_id,
        answer=final_answer,
        source="llm",
        sources=qa_response.sources,
        detected_campus=campus,
        latency_ms=latency_ms,
        pre_rerank_candidates=pre_rerank_candidates,
        post_rerank_candidates=post_rerank_candidates,
        final_reranked_candidates=final_reranked_candidates,
        expanded_contexts=contexts,
    )