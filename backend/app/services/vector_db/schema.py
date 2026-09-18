from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class VectorPoint(BaseModel):
    id: str
    vector: Optional[List[float]] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    id: str
    score: float
    payload: Dict[str, Any] = Field(default_factory=dict)