import asyncio
import logging
import re
from typing import Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.database import async_session
from app.models.org import Org
from app.services.embeddings.factory import get_embedder
from app.services.embeddings.sparse_embedder import get_sparse_embedder
from app.services.llm_qa.factory import get_qa_synthesizer
from app.services.llm_qa.schema import (
    MatchedQuestionDetail,
    QARequest,
    RetrievedContextItem,
)
from app.services.query_pipeline.context_expander import ContextExpander
from app.services.query_pipeline.intent_classifier import QueryClassifier
from app.services.query_pipeline.schema import (
    PipelineQueryRequest,
    PipelineQueryResponse,
)
from app.services.reranker.factory import get_reranker
from app.services.reranker.schema import RerankCandidate
from app.services.semantic_cache.factory import get_semantic_cache
from app.services.semantic_cache.schemas import CacheMetadata
from app.services.vector_db.factory import get_vector_db

logger = logging.getLogger(__name__)


def _normalize_campus(value: Optional[str]) -> Optional[str]:
    """Payload campus values are lowercase URL slugs; make classifier output match."""
    if not value:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug if slug and slug != "main" else None


def _cache_scope(org_id: int, campus: Optional[str]) -> str:
    """Tenant tag used for the semantic cache."""
    if campus:
        return f"{org_id}_{campus.replace('-', '_')}"
    return str(org_id)


class QueryPipeline:
    def __init__(self):
        self.vector_db = get_vector_db()
        self.embedder = get_embedder()
        self.sparse_embedder = get_sparse_embedder()
        self.qa_synthesizer = get_qa_synthesizer()
        self.semantic_cache = get_semantic_cache()
        self.classifier = QueryClassifier()
        self.reranker = get_reranker()
        self.expander = ContextExpander(window=1, expand_top_n=3, max_chars=16000)

    @property
    def collection_name(self) -> str:
        """Always resolves dynamically from settings."""
        return settings.collection_name

    async def _resolve_org_details(self, org_id: int) -> Tuple[str, List[str]]:
        async with async_session() as session:
            org = await session.get(Org, org_id)
            if org:
                return org.name, []
        return "the organization", []

    def _reciprocal_rank_fusion(
        self,
        dense_hits: list,
        sparse_hits: list,
        k: int = 60,
    ) -> List[Tuple[str, float, dict, List[MatchedQuestionDetail]]]:
        chunk_scores: Dict[str, float] = {}
        chunk_payloads: Dict[str, dict] = {}
        chunk_matched: Dict[str, List[MatchedQuestionDetail]] = {}

        for rank, hit in enumerate(dense_hits):
            parent_id = hit.payload.get("parent_chunk_id") or hit.id
            q_text = hit.payload.get("question_text") or ""
            chunk_payloads.setdefault(parent_id, hit.payload)
            chunk_matched.setdefault(parent_id, [])
            if q_text:
                chunk_matched[parent_id].append(
                    MatchedQuestionDetail(
                        question=q_text, score=float(hit.score), method="dense", rank=rank
                    )
                )
            chunk_scores[parent_id] = chunk_scores.get(parent_id, 0.0) + 1.0 / (k + rank + 1)

        seen_sparse: set = set()
        for point_rank, hit in enumerate(sparse_hits):
            parent_id = hit.payload.get("parent_chunk_id") or hit.id
            q_text = hit.payload.get("question_text") or ""
            chunk_payloads.setdefault(parent_id, hit.payload)
            chunk_matched.setdefault(parent_id, [])

            existing = {m.question for m in chunk_matched[parent_id]}
            if q_text and q_text not in existing:
                chunk_matched[parent_id].append(
                    MatchedQuestionDetail(
                        question=q_text, score=float(hit.score), method="sparse", rank=point_rank
                    )
                )
            if parent_id not in seen_sparse:
                chunk_rank = len(seen_sparse)
                seen_sparse.add(parent_id)
                chunk_scores[parent_id] = chunk_scores.get(parent_id, 0.0) + 1.0 / (k + chunk_rank + 1)

        ordered = sorted(chunk_scores.items(), key=lambda item: item[1], reverse=True)
        return [
            (pid, score, chunk_payloads[pid], chunk_matched.get(pid, []))
            for pid, score in ordered
        ]

    async def _hybrid_search(self, dense_vec, sparse_data, flt, limit):
        dense_task = self.vector_db.search(
            collection_name=self.collection_name,
            query_vector=dense_vec,
            limit=limit,
            filters=flt,
            using_vector_name="question_dense",
        )

        async def _sparse():
            if not sparse_data.indices:
                return []
            return await self.vector_db.search_sparse(
                collection_name=self.collection_name,
                sparse_indices=sparse_data.indices,
                sparse_values=sparse_data.values,
                limit=limit,
                filters=flt,
                using_vector_name="chunk_sparse",
            )

        return await asyncio.gather(dense_task, _sparse())

    async def execute(self, req: PipelineQueryRequest) -> PipelineQueryResponse:
        # Server-enforced top_k resolution
        chosen_top_k = req.top_k or settings.default_top_k
        top_k = max(settings.min_top_k, min(chosen_top_k, settings.max_top_k))

        # 1. Compute dense vector (768-dim)
        dense_embed = await self.embedder.embed_one(req.query, task_type="RETRIEVAL_QUERY")
        dense_vec = dense_embed.values

        # 2. Semantic cache fast-path check FIRST (tenant default scope)
        base_cache_scope = str(req.org_id)
        cache_entry = await self.semantic_cache.get(vector=dense_vec, org_id=base_cache_scope)
        if cache_entry:
            cached_contexts = [
                RetrievedContextItem(**item) if isinstance(item, dict) else item
                for item in cache_entry.metadata.extra.get("contexts", [])
            ]
            return PipelineQueryResponse(
                query=req.query,
                answer=cache_entry.response,
                is_cached=True,
                source="cache",
                sources=cache_entry.metadata.extra.get("sources", []),
                contexts=cached_contexts,
            )

        # 3. Cache MISS: Run classifier & sparse BM25 encoding
        org_name, known_locations = await self._resolve_org_details(req.org_id)
        intent, sparse_data = await asyncio.gather(
            self.classifier.classify_intent(
                req.query, org_name=org_name, known_locations=known_locations
            ),
            self.sparse_embedder.embed_query(req.query),
        )

        campus = _normalize_campus(intent.detected_sub_entity)
        final_cache_scope = _cache_scope(req.org_id, campus)

        # If campus is detected, check campus-specific cache scope
        if campus and final_cache_scope != base_cache_scope:
            cache_entry = await self.semantic_cache.get(vector=dense_vec, org_id=final_cache_scope)
            if cache_entry:
                cached_contexts = [
                    RetrievedContextItem(**item) if isinstance(item, dict) else item
                    for item in cache_entry.metadata.extra.get("contexts", [])
                ]
                return PipelineQueryResponse(
                    query=req.query,
                    answer=cache_entry.response,
                    is_cached=True,
                    source="cache",
                    sources=cache_entry.metadata.extra.get("sources", []),
                    contexts=cached_contexts,
                )

        # 4. Hybrid Retrieval in Active Collection
        tenant_filter: Dict[str, str] = {"group_id": str(req.org_id)}
        if campus:
            tenant_filter["campus"] = campus

        candidate_limit = max(top_k * 6, 30)
        dense_hits, sparse_hits = await self._hybrid_search(
            dense_vec, sparse_data, tenant_filter, candidate_limit
        )

        # If campus filter returned nothing, fallback to tenant-wide
        if not dense_hits and not sparse_hits and campus:
            logger.info("No hits with campus=%s, retrying tenant-wide", campus)
            dense_hits, sparse_hits = await self._hybrid_search(
                dense_vec, sparse_data, {"group_id": str(req.org_id)}, candidate_limit
            )

        # 5. RRF Fusion
        fused = self._reciprocal_rank_fusion(dense_hits, sparse_hits, k=60)
        if not fused:
            return PipelineQueryResponse(
                query=req.query,
                answer="No relevant institutional documents could be found for your query.",
                is_cached=False,
                source="fallback",
            )

        # 6. Cross-Encoder Reranking
        rerank_pool_size = max(top_k * 4, 25)
        candidates = [
            RerankCandidate(
                chunk_id=pid,
                content=payload.get("chunk_text") or "",
                initial_score=score,
                payload=payload,
                matched_questions=mqs,
            )
            for pid, score, payload, mqs in fused[:rerank_pool_size]
            if (payload.get("chunk_text") or "").strip()
        ]
        reranked = await self.reranker.rerank(
            query=req.query,
            candidates=candidates,
            top_k=top_k,
            score_threshold=settings.reranker_score_threshold,
        )
        if not reranked:
            return PipelineQueryResponse(
                query=req.query,
                answer="No sufficiently relevant institutional information was found to answer your inquiry.",
                is_cached=False,
                source="fallback",
            )

        # 7. Context Expansion (Postgres small-to-big)
        contexts = await self.expander.expand(req.org_id, reranked)
        source_urls: List[str] = []
        for c in contexts:
            if c.source_url and c.source_url not in source_urls:
                source_urls.append(c.source_url)

        # 8. LLM QA Answer Synthesis
        qa_response = await self.qa_synthesizer.generate_answer(
            QARequest(query=req.query, contexts=contexts), org_name=org_name
        )
        final_answer = qa_response.answer
        if intent.is_ambiguous and intent.clarification_message:
            final_answer += f"\n\n---\n*Note*: {intent.clarification_message}"

        # 9. Store in Semantic Cache
        await self.semantic_cache.set(
            query=req.query,
            vector=dense_vec,
            response=final_answer,
            org_id=final_cache_scope,
            metadata=CacheMetadata(
                extra={
                    "sources": qa_response.sources,
                    "org_id": req.org_id,
                    "contexts": [c.model_dump() for c in contexts],
                }
            ),
        )

        return PipelineQueryResponse(
            query=req.query,
            answer=final_answer,
            is_cached=False,
            source="llm",
            sources=qa_response.sources,
            contexts=contexts,
        )