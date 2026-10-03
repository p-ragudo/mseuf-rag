from typing import List, Optional
from google import genai
from google.genai import types
from app.services.embeddings.base import BaseEmbedder
from app.services.embeddings.schema import EmbedderConfig, EmbeddingResult


class GeminiEmbedder(BaseEmbedder):
    def __init__(self, config: EmbedderConfig) -> None:
        super().__init__(config)
        self.client = genai.Client(api_key=config.api_key)
        self._cached_dimension: Optional[int] = config.output_dimensionality

        # Strip 'models/' prefix if present so the SDK resolves it cleanly
        model_id = config.model_name
        if model_id.startswith("models/"):
            model_id = model_id.replace("models/", "", 1)
        self.model_name = model_id

    def _build_config(self) -> Optional[types.EmbedContentConfig]:
        task_type = self.config.task_type or "RETRIEVAL_QUERY"
        if not task_type and not self.config.output_dimensionality:
            return None
        return types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self.config.output_dimensionality,
        )

    def embed(self, texts: List[str]) -> List[EmbeddingResult]:
        if not texts:
            return []

        config = self._build_config()

        # Pass texts list directly to leverage batch embedding
        response = self.client.models.embed_content(
            model=self.model_name,
            contents=texts,
            config=config,
        )

        return [EmbeddingResult(values=emb.values) for emb in response.embeddings]

    @property
    def dimension(self) -> int:
        if self._cached_dimension is None:
            probe_result = self.embed_one("probe")
            self._cached_dimension = getattr(
                probe_result, "dimension", len(probe_result.values)
            )
        return self._cached_dimension