from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.models.org_member import OrgMember
from app.models.website import Website, WebsiteScrapeStatus
from app.models.website_schedule import WebsiteScrapeSchedule
from app.models.scraped_page import ScrapedPage
from app.schemas.tenant import WebsiteCreate, WebsiteResponse
from app.services.vector_db.factory import get_vector_db
from app.routes.auth import get_current_user

router = APIRouter(prefix="/websites", tags=["Websites"])


@router.post("/", response_model=WebsiteResponse, status_code=status.HTTP_201_CREATED)
async def create_website(
    payload: WebsiteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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

    new_website = Website(
        org_id=payload.org_id,
        url=clean_url,
        status=WebsiteScrapeStatus.PENDING,
        error_message=None,
    )
    db.add(new_website)
    await db.flush()

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


@router.delete("/{website_id}", status_code=status.HTTP_200_OK)
async def delete_website(
    website_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deletes a website, clearing its Qdrant vectors before executing the
    PostgreSQL cascade deletion.
    """
    stmt = (
        select(Website)
        .join(OrgMember, Website.org_id == OrgMember.org_id)
        .where(
            Website.id == website_id,
            OrgMember.user_id == current_user.id,
        )
    )
    res = await db.execute(stmt)
    website = res.scalar_one_or_none()

    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found or unauthorized.",
        )

    # Clean up Qdrant points across all pages for this website
    vector_db = get_vector_db()
    try:
        await vector_db.delete_points(
            collection_name=settings.resolved_collection_name,
            filters={"group_id": str(website.org_id), "web_id": website.id},
        )
    except Exception as e:
        # Proceed with deletion if collection or points do not exist
        pass
    finally:
        await vector_db.close()

    # PostgreSQL CASCADE cleans up pages, schedules, chunks, and questions
    await db.delete(website)
    await db.commit()

    return {"message": f"Website {website_id} and its vector indices were deleted."}