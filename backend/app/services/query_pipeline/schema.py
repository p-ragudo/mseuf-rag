from typing import List, Optional
from pydantic import BaseModel, Field


class PipelineQueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000, description="User question")
    session_id: Optional[str] = Field(None, description="Optional chat session identifier")


class PipelineQueryResponse(BaseModel):
    answer: str
    is_cached: bool = False
    source: str = Field(..., description="'cache', 'llm', or 'fallback'")
    sources: List[str] = Field(default_factory=list, description="Source URLs or reference links")