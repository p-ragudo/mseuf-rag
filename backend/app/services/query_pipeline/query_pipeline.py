import asyncio
from typing import Dict, List, Optional, Tuple
from sqlalchemy import select

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
from app.services.query_pipeline.intent_classifier import QueryClassifier, QueryIntent
from app.services.query_pipeline.schema import (
    PipelineQueryRequest,
    PipelineQueryResponse,
)
from app.services.semantic_cache.factory import get_semantic_cache
from app.services.semantic_cache.schemas import CacheMetadata
from app.services.vector_db.factory import get_vector_db


class QueryPipeline:
    def __init__(self):
        self.vector_db = get_vector_db()
        self.embedder = get_embedder()
        self.sparse_embedder = get_sparse_embedder()
        self.qa_synthesizer = get_qa_synthesizer()
        self.semantic_cache = get_semantic_cache()
        self.classifier = QueryClassifier()
        self.collection_name = settings.collection_name

    async def _resolve_org_details(self, org_id: int) -> Tuple[str, List[str]]:
        """Dynamically retrieves tenant organization name from DB to prevent cross-tenant leaks."""
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
        """
        Pure Reciprocal Rank Fusion (k=60).
        Dense hits accumulate across multiple question points for the same parent chunk.
        Sparse hits are deduplicated per chunk.
        Arbitrary ephemeral/evergreen multipliers are removed.
        """
        chunk_scores: Dict[str, float] = {}
        chunk_payloads: Dict[str, dict] = {}
        chunk_matched_questions: Dict[str, List[MatchedQuestionDetail]] = {}

        # 1. Process Dense Hits: Multi-question accumulation
        for rank, hit in enumerate(dense_hits):
            parent_id = hit.payload.get("parent_chunk_id") or hit.id
            q_text = hit.payload.get("question_text") or ""

            if parent_id not in chunk_payloads:
                chunk_payloads[parent_id] = hit.payload

            if parent_id not in chunk_matched_questions:
                chunk_matched_questions[parent_id] = []

            if q_text:
                chunk_matched_questions[parent_id].append(
                    MatchedQuestionDetail(
                        question=q_text,
                        score=float(hit.score),
                        method="dense",
                        rank=rank,
                    )
                )

            chunk_scores[parent_id] = chunk_scores.get(parent_id, 0.0) + (1.0 / (k + rank + 1))

        # 2. Process Sparse Hits: Deduplicated BM25 score per parent chunk
        seen_sparse_chunks = set()
        for rank, hit in enumerate(sparse_hits):
            parent_id = hit.payload.get("parent_chunk_id") or hit.id
            q_text = hit.payload.get("question_text") or ""

            if parent_id not in chunk_payloads:
                chunk_payloads[parent_id] = hit.payload

            if parent_id not in chunk_matched_questions:
                chunk_matched_questions[parent_id] = []

            existing_questions = {m.question for m in chunk_matched_questions[parent_id]}
            if q_text and q_text not in existing_questions:
                chunk_matched_questions[parent_id].append(
                    MatchedQuestionDetail(
                        question=q_text,
                        score=float(hit.score),
                        method="sparse",
                        rank=rank,
                    )
                )

            if parent_id not in seen_sparse_chunks:
                seen_sparse_chunks.add(parent_id)
                chunk_scores[parent_id] = chunk_scores.get(parent_id, 0.0) + (1.0 / (k + rank + 1))

        sorted_results = sorted(
            chunk_scores.items(), key=lambda item: item[1], reverse=True
        )

        return [
            (
                parent_id,
                score,
                chunk_payloads[parent_id],
                chunk_matched_questions.get(parent_id, []),
            )
            for parent_id, score in sorted_results
        ]

    async def execute(self, req: PipelineQueryRequest) -> PipelineQueryResponse:
        org_name, known_locations = await self._resolve_org_details(req.org_id)

        intent_task = self.classifier.classify_intent(
            req.query, org_name=org_name, known_locations=known_locations
        )
        dense_embed_task = self.embedder.embed_one(req.query, task_type="RETRIEVAL_QUERY")

        intent, dense_embed_result = await asyncio.gather(intent_task, dense_embed_task)
        dense_vec = dense_embed_result.values

        cache_entry = None
        try:
            cache_entry = await self.semantic_cache.get(
                vector=dense_vec,
                org_id=req.org_id,
            )
        except TypeError:
            cache_entry = await self.semantic_cache.get(vector=dense_vec)

        if cache_entry:
            cached_contexts_raw = cache_entry.metadata.extra.get("contexts", [])
            cached_contexts = [
                RetrievedContextItem(**item) if isinstance(item, dict) else item
                for item in cached_contexts_raw
            ]
            return PipelineQueryResponse(
                query=req.query,
                answer=cache_entry.response,
                is_cached=True,
                source="cache",
                sources=cache_entry.metadata.extra.get("sources", []),
                contexts=cached_contexts,
            )

        # Enforce Multi-Tenancy hard filter
        tenant_filter: Dict[str, str] = {"group_id": str(req.org_id)}
        if intent.detected_sub_entity and intent.detected_sub_entity != "main":
            tenant_filter["campus"] = intent.detected_sub_entity

        sparse_data = await self.sparse_embedder.embed_text(req.query)
        candidate_limit = max(req.top_k * 6, 30)

        dense_task = self.vector_db.search(
            collection_name=self.collection_name,
            query_vector=dense_vec,
            limit=candidate_limit,
            filters=tenant_filter,
            using_vector_name="question_dense",
        )
        sparse_task = self.vector_db.search_sparse(
            collection_name=self.collection_name,
            sparse_indices=sparse_data.indices,
            sparse_values=sparse_data.values,
            limit=candidate_limit,
            filters=tenant_filter,
            using_vector_name="chunk_sparse",
        )

        dense_hits, sparse_hits = await asyncio.gather(dense_task, sparse_task)

        fused_candidates = self._reciprocal_rank_fusion(
            dense_hits=dense_hits,
            sparse_hits=sparse_hits,
            k=60,
        )

        top_candidates = fused_candidates[: req.top_k]

        if not top_candidates:
            return PipelineQueryResponse(
                query=req.query,
                answer="No relevant institutional documents could be found for your query.",
                is_cached=False,
                source="fallback",
                sources=[],
                contexts=[],
            )

        contexts: List[RetrievedContextItem] = []
        source_urls: List[str] = []

        for _, _, payload, matched_questions in top_candidates:
            url = payload.get("source_url") or ""
            text = payload.get("chunk_text") or ""
            campus = payload.get("campus") or "main"
            academic_level = payload.get("academic_level") or "general"

            if url and url not in source_urls:
                source_urls.append(url)

            contexts.append(
                RetrievedContextItem(
                    title=url.split("/")[-1] or "Document",
                    content=text,
                    source_url=url,
                    campus=campus,
                    academic_level=academic_level,
                    matched_questions=matched_questions,
                )
            )

        qa_request = QARequest(query=req.query, contexts=contexts)
        qa_response = await self.qa_synthesizer.generate_answer(qa_request, org_name=org_name)

        final_answer = qa_response.answer
        if intent.is_ambiguous and intent.clarification_message:
            final_answer += f"\n\n---\n*Note*: {intent.clarification_message}"

        contexts_dict = [c.model_dump() for c in contexts]
        cache_metadata = CacheMetadata(
            extra={
                "sources": qa_response.sources,
                "org_id": req.org_id,
                "contexts": contexts_dict,
            }
        )

        try:
            await self.semantic_cache.set(
                query=req.query,
                vector=dense_vec,
                response=final_answer,
                org_id=req.org_id,
                metadata=cache_metadata,
            )
        except TypeError:
            await self.semantic_cache.set(
                query=req.query,
                vector=dense_vec,
                response=final_answer,
                metadata=cache_metadata,
            )

        return PipelineQueryResponse(
            query=req.query,
            answer=final_answer,
            is_cached=False,
            source="llm",
            sources=qa_response.sources,
            contexts=contexts,
        )