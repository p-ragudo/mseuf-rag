import asyncio
from typing import List, Optional
from fastembed.rerank.cross_encoder import TextCrossEncoder

from app.services.reranker.base import BaseReranker
from app.services.reranker.schema import RerankCandidate, RerankResult


class FastEmbedReranker(BaseReranker):
    """
    In-process ONNX cross-encoder using `fastembed`.
    Reuses the existing fastembed ONNX runtime dependency already installed
    in the project for BM25.
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        self.model_name = model_name
        # Loads ONNX cross-encoder weights via fastembed
        self.model = TextCrossEncoder(model_name=self.model_name)

    def _sync_rerank(
        self,
        query: str,
        candidates: List[RerankCandidate],
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> List[RerankResult]:
        if not candidates:
            return []

        docs = [c.content for c in candidates]
        # fastembed returns an iterable of similarity scores
        raw_scores = list(self.model.rerank(query=query, documents=docs))

        results: List[RerankResult] = []
        for candidate, score in zip(candidates, raw_scores):
            score_float = float(score)
            if score_threshold is not None and score_float < score_threshold:
                continue

            results.append(
                RerankResult(
                    chunk_id=candidate.chunk_id,
                    content=candidate.content,
                    initial_score=candidate.initial_score,
                    rerank_score=score_float,
                    payload=candidate.payload,
                    matched_questions=candidate.matched_questions,
                )
            )

        results.sort(key=lambda item: item.rerank_score, reverse=True)

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