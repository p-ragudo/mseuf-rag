import asyncio
import time
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

        model_id = config.model_name
        if not model_id.startswith("models/"):
            model_id = f"models/{model_id}"
        self.model_name = model_id

    def _build_config(
        self, task_type: Optional[str] = None
    ) -> Optional[types.EmbedContentConfig]:
        target_task_type = task_type or self.config.task_type or "RETRIEVAL_QUERY"
        if not target_task_type and not self.config.output_dimensionality:
            return None
        return types.EmbedContentConfig(
            task_type=target_task_type,
            output_dimensionality=self.config.output_dimensionality,
        )

    def embed(
        self, texts: List[str], task_type: Optional[str] = None
    ) -> List[EmbeddingResult]:
        if not texts:
            return []

        config = self._build_config(task_type=task_type)
        results: List[EmbeddingResult] = []
        max_retries = 5
        base_delay = 3.0

        # Send up to 50 texts per single HTTP request to preserve quota
        BATCH_SIZE = 50

        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            response = None
            for attempt in range(max_retries):
                try:
                    response = self.client.models.embed_content(
                        model=self.model_name,
                        contents=batch,  # Batch passed directly to SDK
                        config=config,
                    )
                    break
                except Exception as e:
                    err_msg = str(e)
                    if (
                        "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg
                    ) and attempt < max_retries - 1:
                        sleep_time = base_delay * (2 ** attempt)
                        time.sleep(sleep_time)
                    else:
                        raise e

            if response and response.embeddings:
                for emb in response.embeddings:
                    results.append(EmbeddingResult(values=emb.values))

        return results

    @property
    def dimension(self) -> int:
        if self._cached_dimension is None:
            probe_result = self.embed_one("probe", task_type="RETRIEVAL_QUERY")
            self._cached_dimension = getattr(
                probe_result, "dimension", len(probe_result.values)
            )
        return self._cached_dimension