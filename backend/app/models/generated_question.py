from typing import TYPE_CHECKING
from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.chunk import Chunk


class GeneratedQuestion(Base):
    __tablename__ = "generated_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Legacy flag (kept for backwards compatibility)
    is_synced_qdrant: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Model-specific tracking flags for multi-model benchmarking
    is_synced_gemini: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_synced_bge_m3: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    chunk: Mapped["Chunk"] = relationship(back_populates="questions")

    __table_args__ = (
        Index("ix_gen_questions_bge_m3", "is_synced_bge_m3"),
        Index("ix_gen_questions_gemini", "is_synced_gemini"),
    )