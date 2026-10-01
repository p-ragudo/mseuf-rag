from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.user import User
from app.models.org import Org
from app.models.org_member import OrgMember
from app.models.website import Website, WebsiteScrapeStatus
from app.models.website_schedule import WebsiteScrapeSchedule
from app.schemas.tenant import WebsiteCreate, WebsiteResponse, WebsiteScrapeSchedulesResponse
from app.routes.auth import get_current_user

router = APIRouter(prefix="/websites", tags=["Websites"])


@router.post("/", response_model=WebsiteResponse, status_code=status.HTTP_201_CREATED)
async def create_website(
    payload: WebsiteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Registers a new target website under an org and initializes
    its scrape schedule checkpoint.
    """
    # 1. Verify organization exists and current user belongs to it
    membership_res = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == payload.org_id,
            OrgMember.user_id == current_user.id,
        )
    )
    if not membership_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization.",
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
            detail="This website URL is already registered under this organization.",
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lists all registered websites for an organization if the user belongs to it."""
    # Verify user is a member of this org
    membership_res = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == current_user.id,
        )
    )
    if not membership_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization.",
        )

    stmt = select(Website).where(Website.org_id == org_id)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.post("/org/{org_id}/schedules", response_model=list[WebsiteScrapeSchedulesResponse])
async def create_website_schedule(
    org_id: int,
    payload: WebsiteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Creates a scrape schedule for a website under an organization."""
    # Verify user is a member of this org
    membership_res = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == current_user.id,
        )
    )
    if not membership_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization.",
        )

    # Check if the website already exists under this org
    existing_site = await db.execute(
        select(Website).where(
            Website.org_id == org_id,
            Website.url == str(payload.url).rstrip("/"),
        )
    )
    if existing_site.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This website URL is already registered under this organization.",
        )

    # Create Website entry
    new_website = Website(
        org_id=org_id,
        url=str(payload.url).rstrip("/"),
        status=WebsiteScrapeStatus.PENDING,
        error_message=None,
    )
    db.add(new_website)
    await db.flush()

    # Create scrape schedule entry
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

    return [schedule]

@router.get("/org/{org_id}/schedules", response_model=list[WebsiteScrapeSchedulesResponse])
async def list_website_schedules_by_org(
    org_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lists all registered websites and their scrape schedules for an organization if the user belongs to it."""
    # Verify user is a member of this org
    membership_res = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == current_user.id,
        )
    )
    if not membership_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization.",
        )

    stmt = select(WebsiteScrapeSchedule).join(Website).where(Website.org_id == org_id)
    res = await db.execute(stmt)
    return res.scalars().all()

@router.get("/org/{org_id}/schedules/{web_id}", response_model=WebsiteScrapeSchedulesResponse)
async def get_website_schedule(
    org_id: int,
    web_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves the scrape schedule for a specific website under an organization."""
    # Verify user is a member of this org
    membership_res = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == current_user.id,
        )
    )
    if not membership_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization.",
        )

    stmt = select(WebsiteScrapeSchedule).join(Website).where(
        Website.org_id == org_id, Website.id == web_id
    )
    res = await db.execute(stmt)
    schedule = res.scalar_one_or_none()
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scrape schedule not found for the specified website.",
        )

    return schedule

@router.put("/org/{org_id}/schedules/{web_id}", response_model=WebsiteScrapeSchedulesResponse)
async def update_website_schedule(
    org_id: int,
    web_id: int,
    payload: WebsiteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Updates the scrape schedule for a specific website under an organization."""
    # Verify user is a member of this org
    membership_res = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == current_user.id,
        )
    )
    if not membership_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization.",
        )

    stmt = select(WebsiteScrapeSchedule).join(Website).where(
        Website.org_id == org_id, Website.id == web_id
    )
    res = await db.execute(stmt)
    schedule = res.scalar_one_or_none()
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scrape schedule not found for the specified website.",
        )

    # Update the schedule
    schedule.interval_days = payload.interval_days
    schedule.time_of_scrape = payload.time_of_scrape

    await db.commit()
    await db.refresh(schedule)

    return schedule

@router.delete("/org/{org_id}/schedules/{web_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_website_schedule(
    org_id: int,
    web_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deletes the scrape schedule for a specific website under an organization."""
    # Verify user is a member of this org
    membership_res = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == current_user.id,
        )
    )
    if not membership_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization.",
        )

    stmt = select(WebsiteScrapeSchedule).join(Website).where(
        Website.org_id == org_id, Website.id == web_id
    )
    res = await db.execute(stmt)
    schedule = res.scalar_one_or_none()
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scrape schedule not found for the specified website.",
        )

    await db.delete(schedule)
    await db.commit()

    return None

