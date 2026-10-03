import enum
from typing import TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.org import Org
    from app.models.website_schedule import WebsiteScrapeSchedule
    from app.models.scraped_page import ScrapedPage


class WebsiteScrapeStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Website(Base):
    __tablename__ = "websites"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[WebsiteScrapeStatus] = mapped_column(
        Enum(WebsiteScrapeStatus),
        default=WebsiteScrapeStatus.PENDING,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    org: Mapped["Org"] = relationship(back_populates="websites")
    schedule: Mapped["WebsiteScrapeSchedule | None"] = relationship(
        back_populates="website",
        uselist=False,
        cascade="all, delete-orphan",
    )
    pages: Mapped[list["ScrapedPage"]] = relationship(
        back_populates="website",
        cascade="all, delete-orphan",
    )