from typing import Any, Dict, List
from pydantic import BaseModel, Field
from app.services.llm_qa.schema import MatchedQuestionDetail


class RerankCandidate(BaseModel):
    """Candidate document passed from RRF fusion into the cross-encoder reranker."""
    chunk_id: str
    content: str
    initial_score: float = 0.0
    payload: Dict[str, Any] = Field(default_factory=dict)
    matched_questions: List[MatchedQuestionDetail] = Field(default_factory=list)


class RerankResult(BaseModel):
    """Candidate scored and ranked by the cross-encoder."""
    chunk_id: str
    content: str
    initial_score: float
    rerank_score: float
    payload: Dict[str, Any] = Field(default_factory=dict)
    matched_questions: List[MatchedQuestionDetail] = Field(default_factory=list)