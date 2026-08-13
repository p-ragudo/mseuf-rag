from typing import List, Literal
from pydantic import BaseModel, Field
from app.schemas.payload import ChunkContentPayload
from app.core.config import settings

class SearchQueryRequest(BaseModel):
    """
    Payload sent by the frontend on user query.
    """
    query: str = Field(..., min_length=1, description="The user's input search query")
    top_k: int = Field(
        default_factory=lambda: settings.DEFAULT_TOP_K, 
        ge=settings.MIN_TOP_K, 
        le=settings.MAX_TOP_K, 
        description="Number of final unique chunks to return after hybrid reranking"
    )

class SearchResultItem(BaseModel):
    """
    Single unique chunk returned from the retrieval pipeline.
    """
    score: float = Field(
        ..., 
        description="Relevance score (Cosine similarity for cache, RRF score for hybrid search)"
    )
    chunk: ChunkContentPayload = Field(
        ..., 
        description="Full text content and metadata of the retrieved chunk"
    )

class SearchResponse(BaseModel):
    """
    Main response structure sent back to the frontend/chat engine.
    """
    query: str
    source: Literal["cache", "hybrid"] = Field(
        ..., 
        description="Origin layer: 'cache' (Redis Q&A hit) or 'hybrid' (Qdrant + BM25 via RRF)"
    )
    results: List[SearchResultItem]
    execution_time_ms: float = Field(..., description="Total pipeline latency in milliseconds")