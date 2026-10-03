from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class SparseVectorData(BaseModel):
    indices: List[int]
    values: List[float]


class VectorPoint(BaseModel):
    id: str  # UUIDv5 string
    # Can be a single flat list, or a dict of named vectors (dense and/or sparse)
    vector: Optional[
        Union[
            List[float],
            Dict[str, Union[List[float], SparseVectorData, Dict[str, Any]]],
        ]
    ] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    id: str
    score: float
    payload: Dict[str, Any] = Field(default_factory=dict)