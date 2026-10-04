import asyncio
from typing import List, Optional
from sentence_transformers import SentenceTransformer

from app.services.embeddings.base import BaseEmbedder
from app.services.embeddings.schema import EmbedderConfig, EmbeddingResult


class SentenceTransformerEmbedder(BaseEmbedder):
    """
    Standard PyTorch / SentenceTransformers embedder.
    Supports BAAI/bge-m3, Qwen, or any HuggingFace model.
    """

    def __init__(self, config: EmbedderConfig) -> None:
        super().__init__(config)
        self.model_name = config.model_name or "BAAI/bge-m3"
        # Runs on CPU by default
        self.model = SentenceTransformer(self.model_name, device="cpu")
        self._dim = config.output_dimensionality or 1024

    def _sync_embed(self, texts: List[str]) -> List[EmbeddingResult]:
        if not texts:
            return []
        embeddings = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [EmbeddingResult(values=emb.tolist()) for emb in embeddings]

    async def embed(
        self, texts: List[str], task_type: Optional[str] = None
    ) -> List[EmbeddingResult]:
        return await asyncio.to_thread(self._sync_embed, texts)

    @property
    def dimension(self) -> int:
        return self._dim