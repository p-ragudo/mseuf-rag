from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.models.org_member import OrgMember
from app.models.website import Website, WebsiteScrapeStatus
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.models.generated_question import GeneratedQuestion
from app.services.ingest_pipeline.orchestrator import run_full_pipeline, get_active_sync_column
from app.routes.auth import get_current_user

router = APIRouter(prefix="/ingest", tags=["Ingest Pipeline"])

@router.post("/run/{website_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingestion(
    website_id: int,
    background_tasks: BackgroundTasks,
    force_refresh: bool = Query(
        False, description="Forces re-scraping and re-chunking of pages regardless of age"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
            detail=f"Website {website_id} not found or you lack access permissions.",
        )

    if website.status == WebsiteScrapeStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Scrape and ingestion pipeline is already running for this site.",
        )

    background_tasks.add_task(
        run_full_pipeline, website_id=website_id, force_refresh=force_refresh
    )

    return {
        "message": f"Pipeline triggered for {website.url} (force_refresh={force_refresh})",
        "website_id": website.id,
        "status": WebsiteScrapeStatus.IN_PROGRESS,
    }


@router.get("/status/{website_id}")
async def get_ingestion_status(
    website_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
            detail=f"Website {website_id} not found or you lack access permissions.",
        )

    page_counts_res = await db.execute(
        select(ScrapedPage.status, func.count(ScrapedPage.id))
        .where(ScrapedPage.web_id == website_id)
        .group_by(ScrapedPage.status)
    )
    page_stats = {status_val.value: count for status_val, count in page_counts_res.all()}
    total_pages = sum(page_stats.values())

    chunks_count_res = await db.execute(
        select(func.count(Chunk.id))
        .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
        .where(ScrapedPage.web_id == website_id)
    )
    total_chunks = chunks_count_res.scalar_one() or 0

    sync_col = get_active_sync_column()

    q_stats_res = await db.execute(
        select(
            func.count(GeneratedQuestion.id),
            func.count(GeneratedQuestion.id).filter(sync_col.is_(True)),
        )
        .join(Chunk, GeneratedQuestion.chunk_id == Chunk.id)
        .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
        .where(ScrapedPage.web_id == website_id)
    )
    total_questions, synced_model_count = q_stats_res.one()

    return {
        "website_id": website.id,
        "url": website.url,
        "status": website.status,
        "error_message": website.error_message,
        "active_target": {
            "collection_name": settings.resolved_collection_name,
            "sync_column": sync_col.key,
            "provider": settings.embedding_provider,
            "dimension": getattr(settings, "embedding_dimension", settings.vector_dim),
        },
        "checkpoints": {
            "pages": {
                "total_discovered": total_pages,
                "pending": page_stats.get(PageProcessStatus.PENDING.value, 0),
                "in_progress": page_stats.get(PageProcessStatus.IN_PROGRESS.value, 0),
                "completed": page_stats.get(PageProcessStatus.COMPLETED.value, 0),
                "failed": page_stats.get(PageProcessStatus.FAILED.value, 0),
            },
            "chunks": {
                "total": total_chunks,
            },
            "questions": {
                "total_generated": total_questions or 0,
                "synced_active_model": synced_model_count or 0,
            },
        },
    }