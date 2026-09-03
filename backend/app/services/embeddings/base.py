from abc import ABC, abstractmethod
from typing import List
from app.services.embeddings.schema import EmbedderConfig, EmbeddingResult


class BaseEmbedder(ABC):
    def __init__(self, config: EmbedderConfig) -> None:
        self.config = config

    @abstractmethod
    def embed(self, texts: List[str]) -> List[EmbeddingResult]:
        """Embed a list of texts into vectors.
        
        Subclasses should handle internal batching, model prefixes,
        and payload limits.
        """
        pass

    def embed_one(self, text: str) -> EmbeddingResult:
        """Convenience method to embed a single text string."""
        return self.embed([text])[0]

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the vector dimensionality."""
        pass