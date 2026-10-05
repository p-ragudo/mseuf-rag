from typing import List, Optional
from pydantic import BaseModel, Field

from app.services.llm_qa.schema import RetrievedContextItem


class QueryBodyRequest(BaseModel):
    """Client-facing request body schema shown in OpenAPI / Swagger UI."""
    query: str = Field(..., min_length=2, max_length=1000, description="User question")
    session_id: Optional[str] = Field(None, description="Optional chat session identifier")


class PipelineQueryRequest(BaseModel):
    """Internal schema passed across the query pipeline stages."""
    query: str = Field(..., min_length=2, max_length=1000, description="User question")
    org_id: int = Field(..., description="Tenant organization ID passed via URL path")
    session_id: Optional[str] = Field(None, description="Optional chat session identifier")
    top_k: Optional[int] = Field(None, description="Internal top-k override, defaults to server configuration")


class PipelineQueryResponse(BaseModel):
    query: Optional[str] = Field(default=None, description="The incoming user query")
    answer: str
    is_cached: bool = False
    source: str = Field(..., description="'cache', 'llm', or 'fallback'")
    sources: List[str] = Field(default_factory=list, description="Source URLs or reference links")
    contexts: List[RetrievedContextItem] = Field(default_factory=list, description="Passages passed to QA LLM")