from functools import lru_cache
from typing import Dict, Optional, Type

from app.core.config import settings
from app.services.embeddings.base import BaseEmbedder
from app.services.embeddings.schema import EmbedderConfig


class EmbedderFactory:
    _registry: Dict[str, Type[BaseEmbedder]] = {}

    @classmethod
    def register_provider(
        cls, provider_name: str, embedder_cls: Type[BaseEmbedder]
    ) -> None:
        cls._registry[provider_name.strip().lower()] = embedder_cls

    @classmethod
    def create_from_config(cls, config: EmbedderConfig) -> BaseEmbedder:
        provider_key = config.provider.strip().lower()
        embedder_class = cls._registry.get(provider_key)

        if not embedder_class:
            if provider_key == "gemini":
                from app.services.embeddings.gemini_embedder import GeminiEmbedder
                cls.register_provider("gemini", GeminiEmbedder)
                embedder_class = GeminiEmbedder
            elif provider_key in ("fastembed", "local"):
                from app.services.embeddings.fastembed_embedder import FastEmbedEmbedder
                cls.register_provider("fastembed", FastEmbedEmbedder)
                embedder_class = FastEmbedEmbedder
            elif provider_key in ("sentence_transformers", "hf", "huggingface"):
                from app.services.embeddings.sentence_transformer_embedder import SentenceTransformerEmbedder
                cls.register_provider("sentence_transformers", SentenceTransformerEmbedder)
                embedder_class = SentenceTransformerEmbedder
            elif provider_key == "ollama":
                from app.services.embeddings.ollama_embedder import OllamaEmbedder
                cls.register_provider("ollama", OllamaEmbedder)
                embedder_class = OllamaEmbedder
            else:
                available = list(cls._registry.keys()) + ["gemini", "fastembed"]
                raise ValueError(
                    f"Unsupported embedding provider: '{config.provider}'. Available: {available}"
                )

        return embedder_class(config)

    @classmethod
    def create_from_env(cls) -> BaseEmbedder:
        config = EmbedderConfig(
            provider=settings.embedding_provider,
            model_name=settings.embedding_model,
            api_key=settings.embedding_api_key,
            output_dimensionality=settings.embedding_dimension,
            task_type=settings.embedding_task_type,
        )
        return cls.create_from_config(config)

    @classmethod
    def get_embedder(cls, config: Optional[EmbedderConfig] = None) -> BaseEmbedder:
        if config is not None:
            return cls.create_from_config(config)
        return _get_cached_default_embedder()


@lru_cache(maxsize=1)
def _get_cached_default_embedder() -> BaseEmbedder:
    return EmbedderFactory.create_from_env()


def get_embedder(config: Optional[EmbedderConfig] = None) -> BaseEmbedder:
    return EmbedderFactory.get_embedder(config)