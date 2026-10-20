import asyncio
import hashlib
import logging
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
from sqlalchemy import delete, func, select

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
    _bump_content_version,
    get_active_sync_column,
    ingest_uploaded_document,
    run_full_pipeline,
)
from app.services.vector_db.factory import get_vector_db
from app.routes.auth import get_current_user
from app.utils.org_roles import CONTENT_MANAGER_ROLES, require_org_role

router = APIRouter(prefix="/ingest", tags=["Ingest Pipeline"])
logger = logging.getLogger(__name__)

MAX_DOCUMENT_UPLOAD_BYTES = 25 * 1024 * 1024
DOCUMENT_URL_SCHEME = "document://"


def _document_filename(page: ScrapedPage) -> str:
    return unquote(page.url.rsplit("/", 1)[-1])


def _document_status(page: ScrapedPage, website: Website, total_questions: int, synced_questions: int):
    if page.status == PageProcessStatus.FAILED or website.status == WebsiteScrapeStatus.FAILED:
        return PageProcessStatus.FAILED
    if page.status == PageProcessStatus.PENDING:
        return PageProcessStatus.PENDING
    if total_questions and synced_questions == total_questions:
        return PageProcessStatus.COMPLETED
    return PageProcessStatus.IN_PROGRESS


async def _delete_document_vectors(org_id: int, web_id: int) -> None:
    vector_db = get_vector_db()
    try:
        await vector_db.delete_points(
            collection_name=settings.resolved_collection_name,
            filters={"group_id": str(org_id), "web_id": web_id},
        )
    finally:
        await vector_db.close()


async def _get_document_for_member(
    document_id: int,
    current_user: User,
    db: AsyncSession,
) -> tuple[ScrapedPage, Website]:
    result = await db.execute(
        select(ScrapedPage, Website)
        .join(Website, ScrapedPage.web_id == Website.id)
        .join(OrgMember, Website.org_id == OrgMember.org_id)
        .where(
            ScrapedPage.id == document_id,
            ScrapedPage.url.startswith(DOCUMENT_URL_SCHEME),
            OrgMember.user_id == current_user.id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or you lack access permissions.",
        )
    return row


async def _extract_uploaded_file(file: UploadFile) -> tuple[str, str]:
    filename = " ".join(
        Path((file.filename or "").replace("\\", "/")).name.split()
    )
    extension = Path(filename).suffix.lower()
    if extension not in {".pdf", ".doc", ".docx", ".xls", ".xlsx"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, DOC, DOCX, XLS, and XLSX files are supported.",
        )
    if not filename or len(filename) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The document filename must be between 1 and 255 characters.",
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
        text = await asyncio.to_thread(extract_document_text, filename, content)
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
    return filename, text


def _document_markdown(filename: str, category: str, extracted_text: str) -> str:
    escaped_filename = filename.replace("\r", " ").replace("\n", " ")
    escaped_filename = escaped_filename.replace("#", "\\#")
    return f"# {escaped_filename}\n\nCategory: {category}\n\n{extracted_text}"


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
    await require_org_role(
        db,
        website.org_id,
        current_user,
        CONTENT_MANAGER_ROLES,
        "Only organization administrators and ingesters can manage knowledge ingestion.",
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
    category = " ".join(category.split())
    if not category or len(category) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The category must be between 1 and 100 characters.",
        )

    await require_org_role(
        db,
        org_id,
        current_user,
        CONTENT_MANAGER_ROLES,
        "Only organization administrators and ingesters can manage knowledge ingestion.",
    )

    filename, extracted_text = await _extract_uploaded_file(file)

    document_id = uuid4().hex
    markdown_content = _document_markdown(filename, category, extracted_text)
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


@router.get("/documents")
async def list_documents(
    org_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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

    pages_result = await db.execute(
        select(ScrapedPage, Website)
        .join(Website, ScrapedPage.web_id == Website.id)
        .where(
            Website.org_id == org_id,
            Website.url.startswith(DOCUMENT_URL_SCHEME),
        )
        .order_by(ScrapedPage.id.desc())
    )
    pages = pages_result.all()
    if not pages:
        return []

    page_ids = [page.id for page, _website in pages]
    sync_col = get_active_sync_column()
    count_rows = await db.execute(
        select(
            ScrapedPage.id,
            func.count(func.distinct(Chunk.id)),
            func.count(func.distinct(GeneratedQuestion.id)),
            func.count(func.distinct(GeneratedQuestion.id)).filter(sync_col.is_(True)),
        )
        .select_from(ScrapedPage)
        .outerjoin(Chunk, Chunk.page_id == ScrapedPage.id)
        .outerjoin(GeneratedQuestion, GeneratedQuestion.chunk_id == Chunk.id)
        .where(ScrapedPage.id.in_(page_ids))
        .group_by(ScrapedPage.id)
    )
    counts_by_id = {
        page_id: (chunks or 0, questions or 0, synced or 0)
        for page_id, chunks, questions, synced in count_rows.all()
    }

    documents = []
    for page, website in pages:
        chunks, questions, synced = counts_by_id.get(page.id, (0, 0, 0))
        category = ""
        for line in (page.markdown_content or "").splitlines():
            if line.startswith("Category: "):
                category = line.removeprefix("Category: ").strip()
                break
        documents.append(
            {
                "document_id": page.id,
                "filename": _document_filename(page),
                "category": category,
                "status": _document_status(page, website, questions, synced),
                "error_message": website.error_message,
                "chunks": chunks,
                "questions": questions,
                "synced_questions": synced,
            }
        )
    return documents


@router.put("/documents/{document_id}", status_code=status.HTTP_202_ACCEPTED)
async def replace_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    category: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    page, website = await _get_document_for_member(document_id, current_user, db)
    await require_org_role(
        db,
        website.org_id,
        current_user,
        CONTENT_MANAGER_ROLES,
        "Only organization administrators and ingesters can manage knowledge ingestion.",
    )
    if website.status == WebsiteScrapeStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document is currently being ingested.",
        )

    category = " ".join(category.split())
    if not category or len(category) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The category must be between 1 and 100 characters.",
        )
    filename, extracted_text = await _extract_uploaded_file(file)

    try:
        await _delete_document_vectors(page.org_id, website.id)
    except Exception as exc:
        logger.exception("Could not clear old vectors for document %s", document_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not safely replace the document because its existing vectors could not be removed.",
        ) from exc

    page.url = f"{website.url}/{quote(filename, safe='')}"
    page.markdown_content = _document_markdown(filename, category, extracted_text)
    page.content_hash = hashlib.sha256(page.markdown_content.encode("utf-8")).hexdigest()
    page.status = PageProcessStatus.PENDING
    page.chunked_at = None
    page.content_changed_at = datetime.now(timezone.utc)
    page.last_scraped_at = None
    page.qdrant_cleanup_pending = False
    website.status = WebsiteScrapeStatus.IN_PROGRESS
    website.error_message = None
    await db.execute(delete(Chunk).where(Chunk.page_id == page.id))
    await db.commit()
    background_tasks.add_task(ingest_uploaded_document, page_id=page.id)
    return {
        "document_id": page.id,
        "filename": filename,
        "status": PageProcessStatus.PENDING,
        "message": "Replacement document accepted for indexing.",
    }


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    page, website = await _get_document_for_member(document_id, current_user, db)
    await require_org_role(
        db,
        website.org_id,
        current_user,
        CONTENT_MANAGER_ROLES,
        "Only organization administrators and ingesters can manage knowledge ingestion.",
    )
    if website.status == WebsiteScrapeStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document is currently being ingested.",
        )

    try:
        await _delete_document_vectors(page.org_id, website.id)
    except Exception as exc:
        logger.exception("Could not clear vectors for document %s", document_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not safely delete the document because its vectors could not be removed.",
        ) from exc

    await db.delete(website)
    await db.commit()
    try:
        await _bump_content_version(page.org_id)
    except Exception:
        logger.exception("Failed to bump content_version after deleting document %s", document_id)
    return {"message": f"Document {document_id} and its indexed vectors were deleted."}


@router.get("/documents/{document_id}/status")
async def get_document_ingestion_status(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    page, website = await _get_document_for_member(document_id, current_user, db)
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

    document_status = _document_status(page, website, total_questions, synced_questions)

    filename = _document_filename(page)
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