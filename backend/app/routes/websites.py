from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.org import Org
from app.models.website import Website, WebsiteScrapeStatus
from app.models.website_schedule import WebsiteScrapeSchedule
from app.schemas.tenant import WebsiteCreate, WebsiteResponse

router = APIRouter(prefix="/websites", tags=["Websites"])


@router.post("/", response_model=WebsiteResponse, status_code=status.HTTP_201_CREATED)
async def create_website(
    payload: WebsiteCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Registers a new target website under an org and initializes
    its scrape schedule checkpoint.
    """
    # 1. Verify organization exists
    org_res = await db.execute(select(Org).where(Org.id == payload.org_id))
    if not org_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization {payload.org_id} does not exist",
        )

    # 2. Prevent duplicate website URL under the same org
    clean_url = str(payload.url).rstrip("/")
    existing_site = await db.execute(
        select(Website).where(
            Website.org_id == payload.org_id,
            Website.url == clean_url,
        )
    )
    if existing_site.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This website URL is already registered under this organization",
        )

    # 3. Create Website entry
    new_website = Website(
        org_id=payload.org_id,
        url=clean_url,
        status=WebsiteScrapeStatus.PENDING,
        error_message=None,
    )
    db.add(new_website)
    await db.flush()

    # 4. Create default scrape schedule entry
    schedule = WebsiteScrapeSchedule(
        web_id=new_website.id,
        interval_days=payload.interval_days,
        time_of_scrape=payload.time_of_scrape,
        last_scraped_at=None,
        next_scraped_at=None,
    )
    db.add(schedule)

    await db.commit()
    await db.refresh(new_website)

    return new_website


@router.get("/org/{org_id}", response_model=list[WebsiteResponse])
async def list_websites_by_org(
    org_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Lists all registered websites for a specific organization."""
    stmt = select(Website).where(Website.org_id == org_id)
    res = await db.execute(stmt)
    return res.scalars().all()