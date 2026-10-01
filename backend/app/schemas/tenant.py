from datetime import time
from typing import Optional
from pydantic import BaseModel, HttpUrl

from app.models.website import WebsiteScrapeStatus


# --- Org Schemas ---
class OrgCreate(BaseModel):
    name: str


class OrgResponse(BaseModel):
    id: int
    creator_id: int
    name: str

    class Config:
        from_attributes = True

class AddMemberResponse(BaseModel):
   message: str


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

# --- Website Scrape Schedule Schemas ---
class WebsiteScrapeSchedulesResponse(BaseModel):
    id: int
    org_id: int
    url: str
    interval_days: int
    time_of_scrape: time

    class Config:
        from_attributes = True