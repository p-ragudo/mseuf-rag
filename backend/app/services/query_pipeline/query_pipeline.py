import asyncio
from typing import Dict, List, Tuple

from app.core.config import settings
from app.services.embeddings.factory import get_embedder
from app.services.ingest_pipeline.orchestrator import compute_simple_sparse_vector
from app.services.llm_qa.factory import get_qa_synthesizer
from app.services.llm_qa.schema import QARequest, RetrievedContextItem
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
        self.qa_synthesizer = get_qa_synthesizer()
        self.semantic_cache = get_semantic_cache()
        self.collection_name = settings.collection_name

    def _reciprocal_rank_fusion(
        self,
        dense_hits: list,
        sparse_hits: list,
        k: int = 20,
    ) -> List[Tuple[str, float, dict]]:
        """
        Merges dense and sparse ranks using RRF with parent-chunk deduplication.
        Each parent chunk is assigned only its highest-achieved rank per vector space,
        preventing multiple question variations from artificially stacking scores.
        """
        chunk_scores: Dict[str, float] = {}
        chunk_payloads: Dict[str, dict] = {}

        # 1. Deduplicate Dense Hits: Keep only the best-ranking question variation per parent chunk
        seen_dense_chunks = set()
        deduped_dense_ranks = []
        for hit in dense_hits:
            parent_id = hit.payload.get("parent_chunk_id") or hit.id
            if parent_id not in seen_dense_chunks:
                seen_dense_chunks.add(parent_id)
                deduped_dense_ranks.append((parent_id, hit.payload))

        # 2. Score Dense Candidates based on true distinct rank
        for rank, (parent_id, payload) in enumerate(deduped_dense_ranks):
            chunk_payloads[parent_id] = payload
            chunk_scores[parent_id] = chunk_scores.get(parent_id, 0.0) + (1.0 / (k + rank + 1))

        # 3. Deduplicate Sparse Hits: Keep only the best rank per parent chunk
        seen_sparse_chunks = set()
        deduped_sparse_ranks = []
        for hit in sparse_hits:
            parent_id = hit.payload.get("parent_chunk_id") or hit.id
            if parent_id not in seen_sparse_chunks:
                seen_sparse_chunks.add(parent_id)
                deduped_sparse_ranks.append((parent_id, hit.payload))

        # 4. Score Sparse Candidates based on true distinct rank
        for rank, (parent_id, payload) in enumerate(deduped_sparse_ranks):
            if parent_id not in chunk_payloads:
                chunk_payloads[parent_id] = payload
            chunk_scores[parent_id] = chunk_scores.get(parent_id, 0.0) + (1.0 / (k + rank + 1))

        # 5. Apply Evergreen / Ephemeral weighting
        for parent_id, score in chunk_scores.items():
            doc_type = chunk_payloads[parent_id].get("doc_type", "evergreen")
            if doc_type == "evergreen":
                chunk_scores[parent_id] = score * 1.30
            elif doc_type == "ephemeral":
                chunk_scores[parent_id] = score * 0.70

        # 6. Sort descending
        sorted_results = sorted(
            chunk_scores.items(), key=lambda item: item[1], reverse=True
        )
        return [(parent_id, score, chunk_payloads[parent_id]) for parent_id, score in sorted_results]

    async def execute(self, req: PipelineQueryRequest) -> PipelineQueryResponse:
        # Step 1: Precompute dense query vector using RETRIEVAL_QUERY task type
        dense_vec = self.embedder.embed_one(
            req.query, task_type="RETRIEVAL_QUERY"
        ).values

        # Step 2: Semantic Cache Lookup with tenant isolation
        cache_entry = None
        try:
            cache_entry = await self.semantic_cache.get(
                vector=dense_vec,
                org_id=req.org_id,
            )
        except TypeError:
            cache_entry = await self.semantic_cache.get(vector=dense_vec)

        if cache_entry:
            return PipelineQueryResponse(
                query=req.query,
                answer=cache_entry.response,
                is_cached=True,
                source="cache",
                sources=cache_entry.metadata.extra.get("sources", []),
            )

        # Step 3: Compute sparse query vector with stopwords removed
        sparse_data = compute_simple_sparse_vector(req.query)

        # Step 4: Hybrid Multi-Tenant Retrieval using group_id
        candidate_limit = max(req.top_k * 6, 30)
        tenant_filter = {"group_id": str(req.org_id)}

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

        # Step 5: Fusion & Deduplication
        fused_candidates = self._reciprocal_rank_fusion(
            dense_hits=dense_hits,
            sparse_hits=sparse_hits,
            k=20,
        )

        top_candidates = fused_candidates[: req.top_k]

        if not top_candidates:
            return PipelineQueryResponse(
                query=req.query,
                answer="No relevant institutional documents could be found for your query.",
                is_cached=False,
                source="fallback",
                sources=[],
            )

        # Step 6: QA Context Construction
        contexts: List[RetrievedContextItem] = []
        source_urls: List[str] = []

        for _, _, payload in top_candidates:
            url = payload.get("source_url") or ""
            text = payload.get("chunk_text") or ""
            if url and url not in source_urls:
                source_urls.append(url)
            contexts.append(
                RetrievedContextItem(
                    title=url.split("/")[-1] or "Document",
                    content=text,
                    source_url=url,
                )
            )

        qa_request = QARequest(query=req.query, contexts=contexts)
        qa_response = await self.qa_synthesizer.generate_answer(qa_request)

        # Step 7: Populate Semantic Cache
        try:
            await self.semantic_cache.set(
                query=req.query,
                vector=dense_vec,
                response=qa_response.answer,
                org_id=req.org_id,
                metadata=CacheMetadata(
                    extra={"sources": qa_response.sources, "org_id": req.org_id}
                ),
            )
        except TypeError:
            await self.semantic_cache.set(
                query=req.query,
                vector=dense_vec,
                response=qa_response.answer,
                metadata=CacheMetadata(
                    extra={"sources": qa_response.sources, "org_id": req.org_id}
                ),
            )

        return PipelineQueryResponse(
            query=req.query,
            answer=qa_response.answer,
            is_cached=False,
            source="llm",
            sources=qa_response.sources,
        )