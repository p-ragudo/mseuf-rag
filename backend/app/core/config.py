from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # --- RAG Defaults (Safe Fallbacks for Local Dev & Tests) ---
    DEFAULT_TOP_K: int = 5
    MIN_TOP_K: int = 1
    MAX_TOP_K: int = 20

    # --- Domain / Scraping (Strictly Required from .env) ---
    TARGET_DOMAIN: str
    TEST_TARGET_DOMAIN: str

    # --- Infrastructure Secrets (Optional for offline tests, strictly typed) ---
    QDRANT_API_KEY: str | None = None
    QDRANT_CLUSTER_ENDPOINT: str | None = None

    # --- Server Bind Settings (Safe Fallbacks) ---
    HOST: str = "127.0.0.1"
    PORT: int = Field(default=8000, ge=1, le=65535)

    # --- Database ---
    DATABASE_URL: str | None = None
    
    # --- Auth ---
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    @property
    def SERVER_BIND_HOST(self) -> str:
        """Strips protocol prefixes for Uvicorn binding."""
        return (
            self.HOST
            .replace("http://", "")
            .replace("https://", "")
            .split(":")[0]
            .split("/")[0]
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()