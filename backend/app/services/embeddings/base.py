from abc import ABC, abstractmethod
from typing import List, Optional
from app.services.embeddings.schema import EmbedderConfig, EmbeddingResult


class BaseEmbedder(ABC):
    def __init__(self, config: EmbedderConfig) -> None:
        self.config = config

    @abstractmethod
    def embed(
        self, texts: List[str], task_type: Optional[str] = None
    ) -> List[EmbeddingResult]:
        """Embed a list of texts into vectors with an optional task type."""
        pass

    def embed_one(
        self, text: str, task_type: Optional[str] = None
    ) -> EmbeddingResult:
        """Convenience method to embed a single text string."""
        return self.embed([text], task_type=task_type)[0]

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the vector dimensionality."""
        pass