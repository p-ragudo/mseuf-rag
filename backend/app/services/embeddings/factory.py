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
        """Allows embedder implementations to register themselves cleanly."""
        cls._registry[provider_name.strip().lower()] = embedder_cls

    @classmethod
    def create_from_config(cls, config: EmbedderConfig) -> BaseEmbedder:
        provider_key = config.provider.strip().lower()
        embedder_class = cls._registry.get(provider_key)

        if not embedder_class:
            # Fallback dynamic registration for core providers if not yet imported
            if provider_key == "gemini":
                from app.services.embeddings.gemini_embedder import GeminiEmbedder
                cls.register_provider("gemini", GeminiEmbedder)
                embedder_class = GeminiEmbedder
            else:
                available = list(cls._registry.keys())
                raise ValueError(
                    f"Unsupported embedding provider: '{config.provider}'. Available: {available}"
                )

        return embedder_class(config)

    @classmethod
    def create_from_env(cls) -> BaseEmbedder:
        """Builds an EmbedderConfig from application settings and delegates creation."""
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
        """Returns an embedder instance from explicit config or environment defaults."""
        if config is not None:
            return cls.create_from_config(config)
        return _get_cached_default_embedder()


@lru_cache(maxsize=1)
def _get_cached_default_embedder() -> BaseEmbedder:
    """Ensures the default environment-configured embedder is a singleton across requests."""
    return EmbedderFactory.create_from_env()


def get_embedder(config: Optional[EmbedderConfig] = None) -> BaseEmbedder:
    """Convenience module-level entry point (usable directly as a FastAPI Depends)."""
    return EmbedderFactory.get_embedder(config)