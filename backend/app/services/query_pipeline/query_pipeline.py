import logging
from typing import List, Optional

from app.services.embeddings.factory import get_embedder
from app.services.semantic_cache.factory import get_semantic_cache
from app.services.semantic_cache.schemas import CacheMetadata
from app.services.llm_qa.factory import get_qa_synthesizer
from app.services.llm_qa.schema import QARequest, RetrievedContextItem
from app.services.query_pipeline.schema import PipelineQueryRequest, PipelineQueryResponse

# Replace this import with your actual vector_db service/factory
from app.services.vector_db.factory import get_vector_db

logger = logging.getLogger(__name__)

FALLBACK_SCOPE_MESSAGE = (
    "I'm sorry, but your inquiry appears to be outside the scope of my supported topics."
)
FALLBACK_NOT_FOUND_MESSAGE = (
    "I couldn't find any verified information matching your inquiry."
)


class QueryPipelineService:
    def __init__(self):
        self.embedder = get_embedder()
        self.semantic_cache = get_semantic_cache()
        self.qa_synthesizer = get_qa_synthesizer()
        self.vector_db = get_vector_db()

    def _is_within_scope(self, query: str, query_vector: List[float]) -> bool:
        """Determines if the query is in-domain before querying the vector DB.
        
        Can use a lightweight zero-shot classifier, metadata check, or default to True
        if retrieval score threshold acts as scope enforcement.
        """
        return True

    async def execute(self, request: PipelineQueryRequest) -> PipelineQueryResponse:
        user_query = request.query.strip()

        # Step 1: Embed query (embed_one is synchronous on BaseEmbedder)
        embedding_result = self.embedder.embed_one(user_query)
        query_vector = embedding_result.values

        # Step 2: Semantic Cache Check
        cache_hit = await self.semantic_cache.get(query_vector)
        if cache_hit:
            logger.info("Semantic cache hit for query: '%s'", user_query)
            return PipelineQueryResponse(
                answer=cache_hit.response,
                is_cached=True,
                source="cache",
                sources=cache_hit.metadata.extra.get("sources", [])
            )

        # Step 3: Scope Guardrail
        if not self._is_within_scope(user_query, query_vector):
            logger.info("Query rejected by scope filter: '%s'", user_query)
            return PipelineQueryResponse(
                answer=FALLBACK_SCOPE_MESSAGE,
                is_cached=False,
                source="fallback",
                sources=[]
            )

        # Step 4: Vector DB Match
        # Adjust method name to match your app/services/vector_db implementation
        matched_chunks = await self.vector_db.search(query_vector=query_vector, top_k=4)

        if not matched_chunks:
            logger.info("No relevant vector DB records for query: '%s'", user_query)
            return PipelineQueryResponse(
                answer=FALLBACK_NOT_FOUND_MESSAGE,
                is_cached=False,
                source="fallback",
                sources=[]
            )

        # Step 5: Send Context to LLM QA Synthesizer
        context_items = [
            RetrievedContextItem(
                title=getattr(chunk, "title", ""),
                content=chunk.content,
                source_url=getattr(chunk, "source_url", None)
            )
            for chunk in matched_chunks
        ]

        qa_req = QARequest(query=user_query, contexts=context_items)
        qa_res = await self.qa_synthesizer.generate_answer(qa_req)

        # Step 6: Cache QA pair
        chunk_ids = [str(getattr(c, "id", "")) for c in matched_chunks if hasattr(c, "id")]
        cache_metadata = CacheMetadata(
            chunk_ids=chunk_ids,
            extra={"sources": qa_res.sources}
        )
        
        await self.semantic_cache.set(
            query=user_query,
            vector=query_vector,
            response=qa_res.answer,
            metadata=cache_metadata
        )

        return PipelineQueryResponse(
            answer=qa_res.answer,
            is_cached=False,
            source="llm",
            sources=qa_res.sources
        )


def get_query_pipeline() -> QueryPipelineService:
    return QueryPipelineService()