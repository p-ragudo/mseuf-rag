from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, HttpUrl, Field
from app.models.scraped_page import PageProcessStatus


class ScrapePageRequest(BaseModel):
    """Input payload to trigger a scrape job."""
    org_id: int
    web_id: int
    url: HttpUrl


class ScrapeBatchRequest(BaseModel):
    """Input payload to scrape multiple URLs under one tenant."""
    org_id: int
    web_id: int
    urls: List[HttpUrl] = Field(..., min_length=1)


class ScrapedPageResult(BaseModel):
    """Data in transit returned after an operation or passed to downstream workers."""
    id: int
    org_id: int
    web_id: int
    url: str
    status: PageProcessStatus
    markdown_content: Optional[str] = None
    retries: int = 0
    chunked_at: Optional[datetime] = None
    error: Optional[str] = None

    class Config:
        from_attributes = True