from typing import List, Optional
from google import genai
from google.genai import types
from backend.app.services.embeddings.base import BaseEmbedder
from schema import EmbedderConfig, EmbeddingResult


class GeminiEmbedder(BaseEmbedder):
    def __init__(self, config: EmbedderConfig) -> None:
        super().__init__(config)
        self.client = genai.Client(api_key=config.api_key)
        self._cached_dimension: Optional[int] = config.output_dimensionality

    def _build_config(self, task_type: Optional[str]) -> Optional[types.EmbedContentConfig]:
        resolved_task_type = task_type or self.config.task_type
        if not resolved_task_type and not self.config.output_dimensionality:
            return None
        return types.EmbedContentConfig(
            task_type=resolved_task_type,
            output_dimensionality=self.config.output_dimensionality,
        )

    def embed_query(self, text: str) -> EmbeddingResult:
        config = self._build_config(task_type="RETRIEVAL_QUERY")
        response = self.client.models.embed_content(
            model=self.config.model_name,
            contents=text,
            config=config,
        )
        return EmbeddingResult(values=response.embeddings[0].values)

    def embed_documents(self, texts: List[str]) -> List[EmbeddingResult]:
        config = self._build_config(task_type="RETRIEVAL_DOCUMENT")
        response = self.client.models.embed_content(
            model=self.config.model_name,
            contents=texts,
            config=config,
        )
        return [EmbeddingResult(values=emb.values) for emb in response.embeddings]

    @property
    def dimension(self) -> int:
        if self._cached_dimension is None:
            self._cached_dimension = self.embed_query("probe").dimension
        return self._cached_dimension