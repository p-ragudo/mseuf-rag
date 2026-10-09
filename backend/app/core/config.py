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

    # --- Database ---
    DATABASE_URL: str | None = None
    DATABASE_URL_NOT_PROD: str | None = None
    DATABASE_URL_USE_PROD: bool = False

    @computed_field
    @property
    def resolved_database_url(self) -> str:
        if self.DATABASE_URL_USE_PROD:
            return self.DATABASE_URL or ""
        return self.DATABASE_URL_NOT_PROD or self.DATABASE_URL or ""

    # --- Auth ---
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    @property
    def SERVER_BIND_HOST(self) -> str:
        """Strips protocol prefixes for Uvicorn binding."""
        return (
            self.host
            .replace("http://", "")
            .replace("https://", "")
            .split(":")[0]
            .split("/")[0]
        )

    # Test Qdrant
    test_qdrant_api_key: Optional[str] = None
    test_qdrant_cluster_endpoint: Optional[str] = None

    # Collection Names
    dense_collection_name: str = "questions_collection"
    sparse_collection_name: str = "sparse_collection"
    chunk_collection_name: str = "chunks_collection"

    collection_name: str
    collection_name_not_prod: str
    collection_name_use_prod: bool = False

    @computed_field
    @property
    def resolved_collection_name(self) -> str:
        return (
            self.collection_name
            if self.collection_name_use_prod
            else self.collection_name_not_prod
        )

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
    llm_qa_model: str

    # Embedding Service Settings
    embedding_provider: str
    embedding_model: str
    embedding_api_key: Optional[str] = None
    embedding_dimension: Optional[int]
    embedding_task_type: Optional[str] = None

    # Quantization Settings
    quantization_enabled: bool = True
    quantization_type: str = "scalar"  # "scalar" or "binary"
    quantization_always_ram: bool = True
    quantization_rescore: bool = True
    quantization_oversampling: float = 2.0

    vector_dim: int

    # Semantic Cache Settings
    semantic_cache_provider: str
    semantic_cache_url: Optional[str] = None
    semantic_cache_threshold: float = 0.25
    semantic_cache_ttl_seconds: int = 604800
    semantic_cache_index_name: str = "thesis_semantic_cache"
    semantic_cache_index_name_not_prod: str
    semantic_cache_index_name_use_prod: bool = False

    @computed_field
    @property
    def resolved_semantic_cache_name(self) -> str:
        return (
            self.semantic_cache_index_name
            if self.semantic_cache_index_name_use_prod
            else self.semantic_cache_index_name_not_prod
        )

    # Question Generation Script Settings
    script_qgen_use_real_data: bool = False
    script_qgen_min_words_per_chunk: int = 10

    telegram_bot_token: str
    telegram_bot_fastapi_key: str
    telegram_bot_token_not_prod: Optional[str] = None
    telegram_bot_token_fastapi_key_not_prod: Optional[str] = ""
    telegram_bot_use_prod: bool = False

    @computed_field
    @property
    def resolved_telegram_token(self) -> Optional[str]:
        return (
            self.telegram_bot_token
            if self.telegram_bot_use_prod
            else self.telegram_bot_token_not_prod
        )

    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Reranker Settings
    reranker_provider: str = "fastembed"
    reranker_model_name: str = "Xenova/ms-marco-MiniLM-L-12-v2"
    reranker_top_k: int = 5
    reranker_score_threshold: Optional[float] = None
    reranker_batch_size: int = 16
    reranker_max_length: int = 512

    # Huggingface Token
    hf_token: Optional[str] = None

    @computed_field
    @property
    def active_qdrant_endpoint(self) -> Optional[str]:
        return (
            self.test_qdrant_cluster_endpoint
            if self.use_test_qdrant_db
            else self.qdrant_cluster_endpoint
        )

    @computed_field
    @property
    def active_qdrant_api_key(self) -> Optional[str]:
        return (
            self.test_qdrant_api_key
            if self.use_test_qdrant_db
            else self.qdrant_api_key
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()