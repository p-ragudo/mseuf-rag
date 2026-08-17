import os
from typing import Optional

from .qdrant_provider_cloud_inference import QdrantVectorCloudInferenceDB
from .base_vdb import BaseVectorDB
from .qdrant_provider import QdrantVectorDB


def get_vector_db(provider: Optional[str] = None) -> BaseVectorDB:
    provider = provider or os.getenv("VECTOR_DB_PROVIDER", "qdrant").lower()

    if provider == "qdrant":
        return QdrantVectorDB()
    if provider == "qdrant_cloud_inference":
        return QdrantVectorCloudInferenceDB()

    raise ValueError(f"Unsupported Vector DB provider: {provider}")