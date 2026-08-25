from typing import Optional

from app.core.config import settings
from .qdrant_provider_cloud_inference import QdrantCloudInferenceProvider
from .base import BaseVectorDB
from .qdrant_provider import QdrantVectorDB


def get_vector_db(provider: Optional[str] = None) -> BaseVectorDB:
    provider = provider or settings.vector_db_provider.lower()

    if provider == "qdrant":
        return QdrantVectorDB()
    if provider == "qdrant_cloud_inference":
        return QdrantCloudInferenceProvider()

    raise ValueError(f"Unsupported Vector DB provider: {provider}")