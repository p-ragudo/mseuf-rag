from datetime import datetime, time
from typing import Optional
from pydantic import BaseModel, EmailStr, HttpUrl
from typing import Literal

from app.models.website import WebsiteScrapeStatus


# --- Org Schemas ---
class OrgCreate(BaseModel):
    name: str


class OrgMemberCreate(BaseModel):
    email: EmailStr


class OrgResponse(BaseModel):
    id: int
    creator_id: int
    name: str

    class Config:
        from_attributes = True


class PublicOrgResponse(BaseModel):
    """Publicly visible metadata used by the frontend chat page without requiring auth."""
    id: int
    name: str

    class Config:
        from_attributes = True


class OrgMemberSummary(BaseModel):
    user_id: int
    email: str
    first_name: str
    last_name: str
    role: str


class OrgMembersResponse(BaseModel):
    members: list[OrgMemberSummary]
    can_manage: bool


# --- Website Schemas ---
class WebsiteCreate(BaseModel):
    org_id: int
    url: HttpUrl
    # Optional scrape schedule configuration
    interval_days: int = 1
    time_of_scrape: time = time(hour=2, minute=0)


class WebsiteResponse(BaseModel):
    id: int
    org_id: int
    url: str
    status: WebsiteScrapeStatus
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class WebsiteScrapeSchedulesResponse(BaseModel):
    id: int
    web_id: int
    interval_days: int
    time_of_scrape: time
    last_scraped_at: Optional[datetime] = None
    next_scraped_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class FeedbackBodyRequest(BaseModel):
    satisfied: bool | None    

class ChartPoint(BaseModel):
    date: str   # start of the bucket, e.g. "2026-10-13"
    count: int

class StatsRequest(BaseModel):
    org_id: int
    range: Literal["last_7_days", "last_30_days", "last_90_days", "last_year", "all_time"]

class StatsResponse(BaseModel):
    inquiry_count: int
    satisfaction_rate: float
    average_response_time: float  # in milliseconds
    top_10_inquiries: dict[str, int]  # Dictionary of inquiry text and their counts
    top_10_chunks: dict[str, int]  # Dictionary of chunk text and their counts
    top_10_chunks_access_time: dict[str, datetime]  # Dictionary of chunk text and their access times
    chart_data: list[ChartPoint]  # List of chart points

class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
