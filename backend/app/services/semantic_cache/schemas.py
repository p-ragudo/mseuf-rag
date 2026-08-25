from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CacheMetadata(BaseModel):
    doc_ids: List[str] = Field(default_factory=list, description="IDs of source docs used")
    chunk_ids: List[str] = Field(default_factory=list, description="IDs of chunks used")
    confidence_score: Optional[float] = Field(None, description="Retrieval similarity score")
    extra: Dict[str, Any] = Field(default_factory=dict)


class CacheEntry(BaseModel):
    query: str
    response: str
    metadata: CacheMetadata = Field(default_factory=CacheMetadata)
    cached_at: Optional[datetime] = None


class ChatQueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000, description="User's natural language question")
    session_id: Optional[str] = Field(None, description="Optional conversational session ID")


class ChatQueryResponse(BaseModel):
    answer: str
    is_cached: bool = False
    source_chunks: List[str] = Field(default_factory=list)