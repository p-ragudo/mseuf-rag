import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, model_validator

from app.utils.uuid_generator import generate_doc_id, generate_chunk_id


class ScrapedPageStatus(str, Enum):
    SCRAPED = "SCRAPED"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class ChunkStatus(str, Enum):
    PENDING_QGEN = "PENDING_QGEN"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


class ScrapedPage(BaseModel):
    id: Optional[str] = Field(default=None)
    tenant_id: str = Field(..., min_length=1)
    source_url: str = Field(...)
    raw_markdown: str = Field(...)
    content_hash: Optional[str] = Field(default=None)
    status: ScrapedPageStatus = Field(default=ScrapedPageStatus.SCRAPED)
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def populate_deterministic_fields(self) -> "ScrapedPage":
        if not self.id:
            self.id = generate_doc_id(tenant_id=self.tenant_id, source_url=self.source_url)
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.raw_markdown.encode("utf-8")).hexdigest()
        return self


class DocumentChunk(BaseModel):
    id: Optional[str] = Field(default=None)
    scraped_page_id: str = Field(...)
    tenant_id: str = Field(..., min_length=1)
    source_url: str = Field(...)
    title: str = Field(...)
    chunk_index: int = Field(..., ge=0)
    content: str = Field(...)
    content_hash: Optional[str] = Field(default=None)
    status: ChunkStatus = Field(default=ChunkStatus.PENDING_QGEN)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def populate_deterministic_fields(self) -> "DocumentChunk":
        if not self.id:
            self.id = generate_chunk_id(
                tenant_id=self.tenant_id,
                source_url=self.source_url,
                chunk_index=self.chunk_index,
                content=self.content,
            )
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        return self