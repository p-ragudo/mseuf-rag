import asyncio
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

    async def embed(
        self, texts: List[str], task_type: Optional[str] = None
    ) -> List[EmbeddingResult]:
        if not texts:
            return []

<<<<<<< HEAD
        config = self._build_config()

        # Pass texts list directly to leverage batch embedding
        response = self.client.models.embed_content(
            model=self.model_name,
            contents=texts,
            config=config,
        )
=======
        config = self._build_config(task_type=task_type)
        results: List[EmbeddingResult] = []
        max_retries = 5
        base_delay = 3.0

        # Maximum batch size supported by Gemini embed_content
        BATCH_SIZE = 100

        for i in range(0, len(texts), BATCH_SIZE):
            chunk = texts[i : i + BATCH_SIZE]
            
            # Format each text as an independent Content document
            content_batch = [
                types.Content(parts=[types.Part.from_text(text=t)])
                for t in chunk
            ]

            response = None
            for attempt in range(max_retries):
                try:
                    response = await self.client.aio.models.embed_content(
                        model=self.model_name,
                        contents=content_batch,
                        config=config,
                    )
                    break
                except Exception as e:
                    err_msg = str(e)
                    if (
                        "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "503" in err_msg
                    ) and attempt < max_retries - 1:
                        sleep_time = base_delay * (2 ** attempt)
                        print(f"[Gemini Embed Retry] Rate limit hit. Waiting {sleep_time:.1f}s...")
                        await asyncio.sleep(sleep_time)
                    else:
                        raise e

            if response and response.embeddings:
                for emb in response.embeddings:
                    results.append(EmbeddingResult(values=emb.values))
            else:
                raise ValueError(f"Failed to retrieve embeddings for batch {i}..{i+len(chunk)}")
>>>>>>> daa3a40c5315c21c6f4b75be8f393b3cc93e0e6e

        return [EmbeddingResult(values=emb.values) for emb in response.embeddings]

    @property
    def dimension(self) -> int:
        if self._cached_dimension is None:
            return self.config.output_dimensionality or 3072
        return self._cached_dimension