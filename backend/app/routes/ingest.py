from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.website import Website, WebsiteScrapeStatus
from app.services.ingest_pipeline.orchestrator import run_full_pipeline

router = APIRouter(prefix="/ingest", tags=["Ingest Pipeline"])


@router.post("/run/{website_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingestion(
    website_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Triggers discovery, scraping, chunking, and question generation
    for a website in the background.
    """
    res = await db.execute(select(Website).where(Website.id == website_id))
    website = res.scalar_one_or_none()

    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Website {website_id} does not exist",
        )

    if website.status == WebsiteScrapeStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Scrape and ingestion pipeline is already running for this site.",
        )

    # Queue execution
    background_tasks.add_task(run_full_pipeline, website_id=website_id)

    return {
        "message": f"Pipeline triggered for {website.url}",
        "website_id": website.id,
        "status": WebsiteScrapeStatus.IN_PROGRESS,
    }


@router.get("/status/{website_id}")
async def get_ingestion_status(
    website_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Returns the current database checkpoint progress for this website."""
    res = await db.execute(select(Website).where(Website.id == website_id))
    website = res.scalar_one_or_none()

    if not website:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found",
        )

    return {
        "website_id": website.id,
        "url": website.url,
        "status": website.status,
        "error_message": website.error_message,
    }