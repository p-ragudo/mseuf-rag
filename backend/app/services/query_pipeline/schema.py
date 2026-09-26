from typing import List, Optional
from pydantic import BaseModel, Field


class PipelineQueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000, description="User natural language query")
    org_id: int = Field(..., description="Organization ID for multi-tenant isolation")
    top_k: Optional[int] = Field(default=5, ge=1, le=20, description="Number of context passages to retrieve")
    session_id: Optional[str] = Field(None, description="Optional chat session identifier")


class PipelineQueryResponse(BaseModel):
    query: str
    answer: str
    is_cached: bool = False
    source: str = Field(..., description="'cache', 'llm', or 'fallback'")
    sources: List[str] = Field(default_factory=list, description="Source URLs or reference links")