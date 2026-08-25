from abc import ABC, abstractmethod
from typing import List
from schema import EmbedderConfig, EmbeddingResult


class BaseEmbedder(ABC):
    def __init__(self, config: EmbedderConfig) -> None:
        self.config = config

    @abstractmethod
    def embed_query(self, text: str) -> EmbeddingResult:
        """Embed a single search query."""
        pass

    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[EmbeddingResult]:
        """Embed a batch of document texts."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the vector dimensionality."""
        pass