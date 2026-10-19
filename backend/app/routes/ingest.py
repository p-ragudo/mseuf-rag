import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.models.org_member import OrgMember
from app.models.website import Website, WebsiteScrapeStatus
from app.models.scraped_page import ScrapedPage, PageProcessStatus
from app.models.chunk import Chunk
from app.models.generated_question import GeneratedQuestion
from app.services.ingest_pipeline.document_parser import (
    DocumentExtractionError,
    DocumentParserUnavailableError,
    extract_document_text,
)
from app.services.ingest_pipeline.orchestrator import (
    get_active_sync_column,
    ingest_uploaded_document,
    run_full_pipeline,
)
from app.routes.auth import get_current_user

router = APIRouter(prefix="/ingest", tags=["Ingest Pipeline"])

MAX_DOCUMENT_UPLOAD_BYTES = 25 * 1024 * 1024
DOCUMENT_URL_SCHEME = "document://"


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


@router.post("/documents", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    org_id: int = Form(...),
    category: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filename = " ".join(
        Path((file.filename or "").replace("\\", "/")).name.split()
    )
    extension = Path(filename).suffix.lower()
    if extension not in {".pdf", ".doc", ".docx"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, DOC, and DOCX files are supported.",
        )
    if not filename or len(filename) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The document filename must be between 1 and 255 characters.",
        )

    category = " ".join(category.split())
    if not category or len(category) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The category must be between 1 and 100 characters.",
        )

    membership = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == current_user.id,
        )
    )
    if membership.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization.",
        )

    try:
        content = await file.read(MAX_DOCUMENT_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    if len(content) > MAX_DOCUMENT_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Documents must be no larger than 25 MB.",
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded document is empty.",
        )

    try:
        extracted_text = await asyncio.to_thread(
            extract_document_text, filename, content
        )
    except DocumentExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except DocumentParserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    document_id = uuid4().hex
    escaped_filename = filename.replace("\r", " ").replace("\n", " ")
    escaped_filename = escaped_filename.replace("#", "\\#")
    markdown_content = (
        f"# {escaped_filename}\n\n"
        f"Category: {category}\n\n"
        f"{extracted_text}"
    )
    now = datetime.now(timezone.utc)
    website = Website(
        org_id=org_id,
        url=f"{DOCUMENT_URL_SCHEME}{document_id}",
        status=WebsiteScrapeStatus.IN_PROGRESS,
    )
    db.add(website)
    await db.flush()

    page = ScrapedPage(
        org_id=org_id,
        web_id=website.id,
        url=f"{DOCUMENT_URL_SCHEME}{document_id}/{quote(filename, safe='')}",
        markdown_content=markdown_content,
        status=PageProcessStatus.PENDING,
        content_hash=hashlib.sha256(markdown_content.encode("utf-8")).hexdigest(),
        content_changed_at=now,
        last_seen_at=now,
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)

    background_tasks.add_task(ingest_uploaded_document, page_id=page.id)
    return {
        "document_id": page.id,
        "filename": filename,
        "status": PageProcessStatus.PENDING,
        "message": "Document accepted for indexing.",
    }


@router.get("/documents/{document_id}/status")
async def get_document_ingestion_status(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ScrapedPage, Website)
        .join(Website, ScrapedPage.web_id == Website.id)
        .join(OrgMember, Website.org_id == OrgMember.org_id)
        .where(
            ScrapedPage.id == document_id,
            OrgMember.user_id == current_user.id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or you lack access permissions.",
        )

    page, website = row
    sync_col = get_active_sync_column()
    counts = await db.execute(
        select(
            func.count(func.distinct(Chunk.id)),
            func.count(func.distinct(GeneratedQuestion.id)),
            func.count(func.distinct(GeneratedQuestion.id)).filter(sync_col.is_(True)),
        )
        .select_from(ScrapedPage)
        .outerjoin(Chunk, Chunk.page_id == ScrapedPage.id)
        .outerjoin(GeneratedQuestion, GeneratedQuestion.chunk_id == Chunk.id)
        .where(ScrapedPage.id == page.id)
    )
    total_chunks, total_questions, synced_questions = counts.one()

    if page.status == PageProcessStatus.FAILED or website.status == WebsiteScrapeStatus.FAILED:
        document_status = PageProcessStatus.FAILED
    elif page.status == PageProcessStatus.PENDING:
        document_status = PageProcessStatus.PENDING
    elif total_questions and synced_questions == total_questions:
        document_status = PageProcessStatus.COMPLETED
    else:
        document_status = PageProcessStatus.IN_PROGRESS

    filename = unquote(page.url.rsplit("/", 1)[-1])
    return {
        "document_id": page.id,
        "filename": filename,
        "status": document_status,
        "error_message": website.error_message,
        "chunks": total_chunks or 0,
        "questions": total_questions or 0,
        "synced_questions": synced_questions or 0,
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