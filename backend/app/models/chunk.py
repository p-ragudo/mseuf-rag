from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey, Text, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.scraped_page import ScrapedPage


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(
        ForeignKey("scraped_pages.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_qgen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    page: Mapped["ScrapedPage"] = relationship(back_populates="chunks")