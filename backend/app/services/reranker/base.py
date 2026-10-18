from abc import ABC, abstractmethod
from typing import List, Optional
from app.services.reranker.schema import RerankCandidate, RerankResult


class BaseReranker(ABC):
    """Abstract interface for all cross-encoder reranker providers."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        candidates: List[RerankCandidate],
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> List[RerankResult]:
        """
        Reranks a list of candidate documents against a query string.
        """
        pass