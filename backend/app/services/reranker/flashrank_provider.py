import asyncio
from typing import List, Optional
from flashrank import Ranker, RerankRequest

from app.services.reranker.base import BaseReranker
from app.services.reranker.schema import RerankCandidate, RerankResult


class FlashRankReranker(BaseReranker):
    """
    In-process ONNX cross-encoder reranker powered by FlashRank.
    Extremely fast on CPU with no heavy PyTorch dependencies.
    """

    def __init__(self, model_name: str = "ms-marco-MiniLM-L-12-v2", max_length: int = 512):
        self.model_name = model_name
        self.max_length = max_length
        # Initialize Ranker (lazy-loaded or cached by flashrank internally)
        self.ranker = Ranker(model_name=self.model_name, max_length=self.max_length)

    def _sync_rerank(
        self,
        query: str,
        candidates: List[RerankCandidate],
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> List[RerankResult]:
        if not candidates:
            return []

        passages = [
            {"id": c.chunk_id, "text": c.content, "meta": c}
            for c in candidates
        ]

        rerank_req = RerankRequest(query=query, passages=passages)
        ranked_passages = self.ranker.rerank(rerank_req)

        results: List[RerankResult] = []
        for p in ranked_passages:
            score = float(p.get("score", 0.0))
            if score_threshold is not None and score < score_threshold:
                continue

            orig_candidate: RerankCandidate = p["meta"]
            results.append(
                RerankResult(
                    chunk_id=orig_candidate.chunk_id,
                    content=orig_candidate.content,
                    initial_score=orig_candidate.initial_score,
                    rerank_score=score,
                    payload=orig_candidate.payload,
                    matched_questions=orig_candidate.matched_questions,
                )
            )

        results.sort(key=lambda r: r.rerank_score, reverse=True)

        if top_k is not None:
            return results[:top_k]
        return results

    async def rerank(
        self,
        query: str,
        candidates: List[RerankCandidate],
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> List[RerankResult]:
        return await asyncio.to_thread(
            self._sync_rerank, query, candidates, top_k, score_threshold
        )