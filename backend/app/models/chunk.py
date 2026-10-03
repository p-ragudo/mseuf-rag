from typing import TYPE_CHECKING, Optional
from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.scraped_page import ScrapedPage
    from app.models.generated_question import GeneratedQuestion


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(
        ForeignKey("scraped_pages.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_qgen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Structure-aware chunk metadata
    chunk_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    section_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    heading_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    part_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    part_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    qgen_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    page: Mapped["ScrapedPage"] = relationship(back_populates="chunks")
    questions: Mapped[list["GeneratedQuestion"]] = relationship(
        back_populates="chunk",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_chunks_has_qgen_attempts", "has_qgen", "qgen_attempts"),
    )