from datetime import time, datetime
from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey, Integer, Time, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.website import Website


class WebsiteScrapeSchedule(Base):
    __tablename__ = "website_scrape_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    web_id: Mapped[int] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    interval_days: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    time_of_scrape: Mapped[time] = mapped_column(Time, nullable=False)
    last_scraped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_scraped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    website: Mapped["Website"] = relationship(back_populates="schedule")