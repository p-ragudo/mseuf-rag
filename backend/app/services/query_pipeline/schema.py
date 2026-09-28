from typing import List, Optional
from pydantic import BaseModel, Field

from app.services.llm_qa.schema import RetrievedContextItem

class PipelineQueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000, description="User question")
    org_id: int = Field(default=1, description="Tenant organization ID")
    top_k: int = Field(default=5, description="Number of context passages to retrieve")
    session_id: Optional[str] = Field(None, description="Optional chat session identifier")


class PipelineQueryResponse(BaseModel):
    query: Optional[str] = Field(default=None, description="The incoming user query")
    answer: str
    is_cached: bool = False
    source: str = Field(..., description="'cache', 'llm', or 'fallback'")
    sources: List[str] = Field(default_factory=list, description="Source URLs or reference links")
    contexts: List[RetrievedContextItem] = Field(default_factory=list, description="Passages passed to QA LLM")