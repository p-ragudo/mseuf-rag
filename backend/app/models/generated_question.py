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
    is_synced_qdrant: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    chunk: Mapped["Chunk"] = relationship(back_populates="questions")

    __table_args__ = (
        Index("ix_generated_questions_is_synced", "is_synced_qdrant"),
    )