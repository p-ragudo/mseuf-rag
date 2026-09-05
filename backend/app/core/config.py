from functools import lru_cache
from typing import Optional
from pydantic import HttpUrl, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App & Server Configuration
    development: bool = True
    host: str
    port: int = 8000

    # Target Domains
    target_domain: str
    test_target_domain: str

    # Vector Database Settings
    vector_db_provider: str
    vector_db_embedding_model: str
    qdrant_embedding_model: str
    use_test_qdrant_db: bool = True

    # Production Qdrant
    qdrant_api_key: Optional[str] = None
    qdrant_cluster_endpoint: Optional[str] = None

    # Test Qdrant
    test_qdrant_api_key: Optional[str] = None
    test_qdrant_cluster_endpoint: Optional[str] = None

    # Collection Names
    dense_collection_name: str = "questions_collection"
    sparse_collection_name: str = "sparse_collection"
    chunk_collection_name: str = "chunks_collection"

    # Retrieval Constraints
    default_top_k: int = 5
    min_top_k: int = 1
    max_top_k: int = 20

    # LLM QGEN Settings
    llm_qgen_provider: str
    llm_qgen_api_key: str
    llm_qgen_model: str

    # LLM QA Settings
    llm_qa_provider: str
    llm_qa_api_key: str
    llm_qgen_model: str

    # Embedding Service Settings
    embedding_provider: str
    embedding_model: str
    embedding_api_key: str
    embedding_dimension: Optional[int] = None
    embedding_task_type: Optional[str] = None

    vector_dim: int

    # Semantic Cache Settings
    semantic_cache_provider: str
    semantic_cache_url: Optional[str] = None
    semantic_cache_threshold: float = 0.25
    semantic_cache_ttl_seconds: int = 604800
    semantic_cache_index_name: str = "thesis_semantic_cache"

    # Question Generation Script Settings
    script_qgen_use_real_data: bool = False
    script_qgen_min_words_per_chunk: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,  # Reads uppercase .env keys into lowercase attributes
    )

    @computed_field
    @property
    def active_qdrant_endpoint(self) -> Optional[str]:
        """Dynamically returns test or production endpoint based on USE_TEST_QDRANT_DB."""
        return (
            self.test_qdrant_cluster_endpoint
            if self.use_test_qdrant_db
            else self.qdrant_cluster_endpoint
        )

    @computed_field
    @property
    def active_qdrant_api_key(self) -> Optional[str]:
        """Dynamically returns test or production API key based on USE_TEST_QDRANT_DB."""
        return (
            self.test_qdrant_api_key
            if self.use_test_qdrant_db
            else self.qdrant_api_key
        )


@lru_cache
def get_settings() -> Settings:
    """Cached singleton instance of the settings."""
    return Settings()


settings = get_settings()