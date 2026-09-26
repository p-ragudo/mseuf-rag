import asyncio
from typing import Dict, List, Tuple
from app.core.config import settings
from app.services.embeddings.factory import get_embedder
from app.services.semantic_cache.factory import get_semantic_cache
from app.services.semantic_cache.schemas import CacheMetadata
from app.services.vector_db.factory import get_vector_db
from app.services.vector_db.schema import SearchResult
from app.services.ingest_pipeline.orchestrator import compute_simple_sparse_vector
from app.services.llm_qa.factory import get_qa_synthesizer
from app.services.llm_qa.schema import QARequest, RetrievedContextItem
from .schema import PipelineQueryRequest, PipelineQueryResponse

FALLBACK_RESPONSE = (
    "I'm sorry, but I couldn't find sufficient information in the knowledge base "
    "to answer your question."
)


def apply_rrf(
    dense_results: List[SearchResult],
    sparse_results: List[SearchResult],
    k: int = 60,
) -> List[Tuple[SearchResult, float]]:
    scores: Dict[str, float] = {}
    item_lookup: Dict[str, SearchResult] = {}

    for rank, hit in enumerate(dense_results):
        scores[hit.id] = scores.get(hit.id, 0.0) + (1.0 / (k + rank + 1))
        item_lookup[hit.id] = hit

    for rank, hit in enumerate(sparse_results):
        scores[hit.id] = scores.get(hit.id, 0.0) + (1.0 / (k + rank + 1))
        if hit.id not in item_lookup:
            item_lookup[hit.id] = hit

    sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [(item_lookup[doc_id], score) for doc_id, score in sorted_items]


class QueryPipeline:
    def __init__(self):
        self.embedder = get_embedder()
        self.cache = get_semantic_cache()
        self.vector_db = get_vector_db()
        self.qa_synthesizer = get_qa_synthesizer()
        self.collection_name = settings.collection_name

    async def execute(self, req: PipelineQueryRequest) -> PipelineQueryResponse:
        # Step 1: External Dense & Sparse Encoding (NO Qdrant / Redis vector inference)
        dense_embedding = self.embedder.embed_one(req.query).values
        sparse_embedding = compute_simple_sparse_vector(req.query)

        # Step 2: Semantic Cache Lookup scoped to the tenant
        cached_entry = await self.cache.get(
            vector=dense_embedding,
            org_id=req.org_id,
        )
        if cached_entry:
            sources = (
                cached_entry.metadata.extra.get("sources", [])
                if cached_entry.metadata and cached_entry.metadata.extra
                else []
            )
            return PipelineQueryResponse(
                query=req.query,
                answer=cached_entry.response,
                is_cached=True,
                source="cache",
                sources=sources,
            )

        # Step 3: Hard-isolated Multi-Tenant Retrieval (question_dense + chunk_sparse)
        tenant_filter = {"group_id": str(req.org_id)}
        top_k = req.top_k or settings.default_top_k

        dense_task = self.vector_db.search(
            collection_name=self.collection_name,
            query_vector=dense_embedding,
            limit=top_k * 2,
            filters=tenant_filter,
            using_vector_name="question_dense",
        )

        sparse_task = self.vector_db.search_sparse(
            collection_name=self.collection_name,
            sparse_indices=sparse_embedding.indices,
            sparse_values=sparse_embedding.values,
            limit=top_k * 2,
            filters=tenant_filter,
            using_vector_name="chunk_sparse",
        )

        dense_hits, sparse_hits = await asyncio.gather(dense_task, sparse_task)

        # Step 4: Hybrid RRF Reranking
        fused_results = apply_rrf(dense_hits, sparse_hits)
        if not fused_results:
            return PipelineQueryResponse(
                query=req.query,
                answer=FALLBACK_RESPONSE,
                is_cached=False,
                source="fallback",
                sources=[],
            )

        # Deduplicate by parent_chunk_id (multiple generated questions point to same chunk)
        seen_chunks = set()
        deduped_hits: List[SearchResult] = []
        for hit, _ in fused_results:
            parent_id = hit.payload.get("parent_chunk_id") or hit.id
            if parent_id not in seen_chunks:
                seen_chunks.add(parent_id)
                deduped_hits.append(hit)
            if len(deduped_hits) >= top_k:
                break

        # Step 5: Pack context & synthesize via LLM QA
        contexts: List[RetrievedContextItem] = []
        for hit in deduped_hits:
            payload = hit.payload
            chunk_text = payload.get("chunk_text") or payload.get("question_text", "")
            source_url = payload.get("source_url")
            contexts.append(
                RetrievedContextItem(
                    title=f"Doc {str(payload.get('parent_chunk_id', ''))[:8]}",
                    content=chunk_text,
                    source_url=source_url,
                )
            )

        qa_response = await self.qa_synthesizer.generate_answer(
            QARequest(query=req.query, contexts=contexts)
        )

        # Step 6: Store QA result into semantic cache tagged with org_id
        cache_metadata = CacheMetadata(
            chunk_ids=list(seen_chunks),
            confidence_score=fused_results[0][1] if fused_results else None,
            extra={"sources": qa_response.sources},
        )
        await self.cache.set(
            query=req.query,
            vector=dense_embedding,
            response=qa_response.answer,
            org_id=req.org_id,
            metadata=cache_metadata,
        )

        return PipelineQueryResponse(
            query=req.query,
            answer=qa_response.answer,
            is_cached=False,
            source="llm",
            sources=qa_response.sources,
        )