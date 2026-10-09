import enum
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.org import Org
    from app.models.website import Website
    from app.models.chunk import Chunk


class PageProcessStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ScrapedPage(Base):
    __tablename__ = "scraped_pages"
    __table_args__ = (
        UniqueConstraint("org_id", "web_id", "url", name="uq_scraped_pages_org_web_url"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    web_id: Mapped[int] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    markdown_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PageProcessStatus] = mapped_column(
        Enum(PageProcessStatus),
        default=PageProcessStatus.PENDING,
        nullable=False,
    )
    chunked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # --- Freshness / change tracking ---
    # sha256 of whitespace-normalised cleaned markdown; unchanged hash => skip re-chunk/qgen/embed
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # start year of the academic period this page is about (2025 => AY 2025-2026), if detectable
    doc_period: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # when WE first saw this version of the content
    content_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # stamped by discovery; pages not seen in a later successful discovery are purged
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # True when old Qdrant points of this page may exist and must be swept
    qdrant_cleanup_pending: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )

    # Relationships
    org: Mapped["Org"] = relationship()
    website: Mapped["Website"] = relationship(back_populates="pages")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="page",
        cascade="all, delete-orphan",
    )