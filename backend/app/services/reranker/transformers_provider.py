import asyncio
from typing import List, Optional
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.services.reranker.base import BaseReranker
from app.services.reranker.schema import RerankCandidate, RerankResult


class TransformersReranker(BaseReranker):
    """
    Standard PyTorch cross-encoder using HuggingFace Transformers.
    Runs on CUDA, MPS, or CPU with automatic precision selection.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-base",
        max_length: int = 512,
        batch_size: int = 16,
    ):
        self.model_name = model_name
        self.max_length = max_length
        self.batch_size = batch_size

        if torch.cuda.is_available():
            self.device = torch.device("cuda")
            self.dtype = torch.float16
        elif torch.backends.mps.is_available():
            self.device = torch.device("mps")
            self.dtype = torch.float32
        else:
            self.device = torch.device("cpu")
            self.dtype = torch.float32

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            self.model_name,
            torch_dtype=self.dtype,
        )
        self.model.to(self.device)
        self.model.eval()

    def _sync_rerank(
        self,
        query: str,
        candidates: List[RerankCandidate],
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> List[RerankResult]:
        if not candidates:
            return []

        pairs = [[query, c.content] for c in candidates]
        scores: List[float] = []

        with torch.no_grad():
            for i in range(0, len(pairs), self.batch_size):
                batch_pairs = pairs[i : i + self.batch_size]
                inputs = self.tokenizer(
                    batch_pairs,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                logits = self.model(**inputs).logits

                if logits.shape[-1] == 1:
                    batch_scores = logits.view(-1).float().cpu().tolist()
                else:
                    batch_scores = logits[:, 1].float().cpu().tolist()

                scores.extend(batch_scores)

        results: List[RerankResult] = []
        for c, score in zip(candidates, scores):
            if score_threshold is not None and score < score_threshold:
                continue
            results.append(
                RerankResult(
                    chunk_id=c.chunk_id,
                    content=c.content,
                    initial_score=c.initial_score,
                    rerank_score=score,
                    payload=c.payload,
                    matched_questions=c.matched_questions,
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