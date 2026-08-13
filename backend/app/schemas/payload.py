from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field

class QuestionVectorPayload(BaseModel):
    """
    Shape of the payload stored directly inside each Qdrant vector point.
    Each vector represents ONE generated question pointing to a parent chunk.
    """
    chunk_id: str = Field(..., description="Unique deterministic hash/ID of the parent chunk")
    document_id: Optional[str] = Field(default=None, description="Identifier of the source document")
    source_url: str = Field(..., description="Link to source document/webpage")
    page_title: Optional[str] = Field(default=None, description="Title of the webpage for UI citations")
    generated_question: str = Field(..., description="The specific generated question this vector represents")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC ISO-8601 timestamp"
    )

class ChunkContentPayload(BaseModel):
    """
    Core data shape representing a single text chunk and its metadata.
    Used across hydration layers and retrieval pipelines after chunk selection.
    """
    chunk_id: str = Field(..., description="Unique deterministic hash/ID of the chunk")
    document_id: str = Field(..., description="Unique hash/ID of the parent scraped document/URL")
    source_url: str = Field(..., description="Link to source document/webpage")
    page_title: Optional[str] = Field(default=None, description="Title of the webpage for UI citations")
    content: str = Field(..., description="The raw chunk text evaluated during RAG")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC ISO-8601 timestamp"
    )

class QAPairCache(BaseModel):
    """
    Shape of cached prompt/response entries in Redis.
    """
    query_hash: str = Field(..., description="SHA-256 hash of normalized user query")
    query_text: str
    answer_text: str
    similarity_score: float
    retrieved_chunk_ids: List[str] = Field(
        default_factory=list, 
        description="List of parent chunk_ids used to produce this cached response"
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC ISO-8601 timestamp"
    )