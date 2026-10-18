from typing import List, Optional
import httpx

from app.services.embeddings.base import BaseEmbedder
from app.services.embeddings.schema import EmbedderConfig, EmbeddingResult


class OllamaEmbedder(BaseEmbedder):
    """
    High-performance local embedding provider using Ollama.
    Bypasses Hugging Face completely and executes locally on CPU.
    """

    def __init__(self, config: EmbedderConfig) -> None:
        super().__init__(config)
        self.model_name = config.model_name or "bge-m3"
        self._dim = config.output_dimensionality or 1024
        # Defaults to local Ollama daemon port
        self.base_url = "http://localhost:11434"

    async def embed(
        self, texts: List[str], task_type: Optional[str] = None
    ) -> List[EmbeddingResult]:
        if not texts:
            return []

        results: List[EmbeddingResult] = []
        async with httpx.AsyncClient(base_url=self.base_url, timeout=60.0) as client:
            for text in texts:
                clean_text = text.strip()
                if not clean_text:
                    results.append(EmbeddingResult(values=[0.0] * self._dim))
                    continue

                response = await client.post(
                    "/api/embeddings",
                    json={"model": self.model_name, "prompt": clean_text},
                )
                response.raise_for_status()
                data = response.json()
                results.append(EmbeddingResult(values=data["embedding"]))

        return results

    @property
    def dimension(self) -> int:
        return self._dim