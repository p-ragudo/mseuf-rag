import os
from typing import Dict, Optional, Type
from dotenv import load_dotenv

from backend.app.services.embeddings.base import BaseEmbedder
from gemini_embedder import GeminiEmbedder
from schema import EmbedderConfig

load_dotenv()


class EmbedderFactory:
    _registry: Dict[str, Type[BaseEmbedder]] = {
        "gemini": GeminiEmbedder,
    }

    @classmethod
    def register_provider(cls, provider_name: str, embedder_cls: Type[BaseEmbedder]) -> None:
        cls._registry[provider_name.lower()] = embedder_cls

    @classmethod
    def create_from_config(cls, config: EmbedderConfig) -> BaseEmbedder:
        embedder_class = cls._registry.get(config.provider.lower())
        if not embedder_class:
            raise ValueError(f"Unsupported embedding provider: {config.provider}")
        return embedder_class(config)

    @classmethod
    def create_from_env(cls) -> BaseEmbedder:
        provider = os.getenv("EMBEDDING_PROVIDER")
        model_name = os.getenv("EMBEDDING_MODEL")
        api_key = os.getenv("EMBEDDING_API_KEY")

        if not provider:
            raise ValueError("Environment variable 'EMBEDDING_PROVIDER' is required.")
        if not model_name:
            raise ValueError("Environment variable 'EMBEDDING_MODEL' is required.")
        if not api_key:
            raise ValueError("Environment variable 'EMBEDDING_API_KEY' is required.")

        raw_dim = os.getenv("EMBEDDING_DIMENSION")
        output_dim = int(raw_dim) if raw_dim else None
        task_type = os.getenv("EMBEDDING_TASK_TYPE")

        config = EmbedderConfig(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            output_dimensionality=output_dim,
            task_type=task_type,
        )
        return cls.create_from_config(config)

    @classmethod
    def get_embedder(cls, config: Optional[EmbedderConfig] = None) -> BaseEmbedder:
        """Main entry point: returns an embedder instance from explicit config or .env."""
        if config is not None:
            return cls.create_from_config(config)
        return cls.create_from_env()


# Convenience module-level shortcut
def get_embedder(config: Optional[EmbedderConfig] = None) -> BaseEmbedder:
    return EmbedderFactory.get_embedder(config)