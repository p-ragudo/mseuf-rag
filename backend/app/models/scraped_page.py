import enum
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, Enum, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.org import Org
    from app.models.website import Website
    from app.models.chunk import Chunk


class PageProcessStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ScrapedPage(Base):
    __tablename__ = "scraped_pages"

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
    chunked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    org: Mapped["Org"] = relationship()
    website: Mapped["Website"] = relationship(back_populates="pages")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="page",
        cascade="all, delete-orphan",
    )