from abc import ABC, abstractmethod
from typing import List, Optional
from app.services.embeddings.schema import EmbedderConfig, EmbeddingResult


class BaseEmbedder(ABC):
    def __init__(self, config: EmbedderConfig) -> None:
        self.config = config

    @abstractmethod
    async def embed(
        self, texts: List[str], task_type: Optional[str] = None
    ) -> List[EmbeddingResult]:
        """Embed a list of texts into vectors asynchronously."""
        pass

    async def embed_one(
        self, text: str, task_type: Optional[str] = None
    ) -> EmbeddingResult:
        """Convenience method to embed a single text string asynchronously."""
        res = await self.embed([text], task_type=task_type)
        return res[0]

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the vector dimensionality."""
        pass