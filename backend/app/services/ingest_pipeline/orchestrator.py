import asyncio
import hashlib
import logging
import re
import traceback
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from sqlalchemy import delete, or_, select, update, func

from app.core.config import settings
from app.core.database import async_session
from app.models.chunk import Chunk
from app.models.generated_question import GeneratedQuestion
from app.models.org import Org
from app.models.scraped_page import PageProcessStatus, ScrapedPage
from app.models.website import Website, WebsiteScrapeStatus
from app.services.embeddings.factory import get_embedder
from app.services.embeddings.sparse_embedder import get_sparse_embedder
from app.services.ingest_pipeline.chunk import process_and_chunk_pages
from app.services.ingest_pipeline.chunker import (  # noqa: F401
    estimate_token_count,
    is_substantive_chunk,
)
from app.services.ingest_pipeline.clean_markdown import clean_markdown
from app.services.ingest_pipeline.discovery import run_discovery
from app.services.llm_qgen.factory import get_question_generator
from app.services.llm_qgen.schema import RawChunk
from app.services.vector_db.factory import get_vector_db
from app.services.vector_db.schema import SparseVectorData, VectorPoint
from app.utils.temporal import extract_doc_period
from app.utils.uuid_generator import generate_chunk_id, generate_doc_id, generate_question_id

logger = logging.getLogger(__name__)

QGEN_MAX_ATTEMPTS = 3
SYNC_MAX_CONSECUTIVE_FAILURES = 5
# Re-scrape pages whose last scrape is older than this when a run is triggered.
DEFAULT_REFRESH_AFTER_HOURS = 12.0
# Safety valve: if more than this fraction of known pages looks "missing" after
# discovery, assume discovery degraded (blocked, fallback crawl) and purge nothing.
PURGE_MAX_FRACTION = 0.5


def get_active_sync_column():
    """
    Dynamically maps current environment settings to the corresponding
    tracking column on GeneratedQuestion. Avoids manual code edits when
    switching models in .env.
    """
    provider = (settings.embedding_provider or "").strip().lower()
    dim = getattr(settings, "embedding_dimension", None) or getattr(settings, "vector_dim", 768)

    if provider == "gemini":
        col_name = "is_synced_gemini_768" if dim == 768 else "is_synced_gemini"
    elif "bge" in provider or "bge" in (settings.embedding_model or "").lower():
        col_name = "is_synced_bge_m3"
    else:
        col_name = "is_synced_qdrant"

    return getattr(GeneratedQuestion, col_name, GeneratedQuestion.is_synced_qdrant)


def extract_sub_entity_from_url(url: str) -> str:
    """
    Parses the root sub-path (e.g. 'calauag', 'candelaria') as the sub-entity.
    Generic site sections are ignored so that '/admissions/...' is not mistaken for a campus.
    """
    parsed = urlparse(url)
    segments = [s.strip().lower() for s in parsed.path.split("/") if s.strip()]
    if segments:
        candidate = segments[0]
        ignored = {
            "pages", "news", "announcement", "announcements", "events", "about",
            "article", "posts", "home", "index", "admission", "admissions",
            "academics", "programs", "apply", "contact", "scholarships",
            "tuition", "student-life", "services",
        }
        if candidate not in ignored:
            return candidate
    return "main"


def classify_academic_level(url: str, text: str = "") -> str:
    path = urlparse(url).path.lower()
    lower_text = text[:400].lower()

    if "senior-high" in path or "strand" in lower_text or "shs" in path:
        return "shs"
    if "basic-education" in path or "elementary" in path or "junior-high" in path:
        return "basic_ed"
    if "undergraduate" in path:
        return "undergraduate"
    if re.search(r"(?<!under)graduate", path) or "master" in lower_text or "doctor" in lower_text:
        return "graduate"
    return "undergraduate"


def classify_document_type(url: str, text: str = "") -> str:
    path = urlparse(url).path.lower()
    ephemeral_indicators = [
        "/news", "/announcement", "/announcements",
        "/events", "/event", "/blog", "/posts", "/press",
        "/memorandum", "/advisory", "/bulletin",
    ]
    if any(token in path for token in ephemeral_indicators):
        return "ephemeral"

    if re.search(r"/(?:19|20)\d{2}/", path):
        return "ephemeral"

    current_year = datetime.now().year
    for m in re.finditer(r"a\.?y\.?\s*(20\d{2})", text[:600].lower()):
        if int(m.group(1)) <= current_year - 2:
            return "ephemeral"

    return "evergreen"


# --------------------------------------------------------------------------- #
# Scraping with change detection
# --------------------------------------------------------------------------- #
def _hash_markdown(markdown: str) -> str:
    """Hash of the CLEANED text, so link/tracking/markup noise doesn't count as a change."""
    normalized = re.sub(r"\s+", " ", clean_markdown(markdown or "")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _apply_scrape_result(page: ScrapedPage, markdown: str) -> bool:
    """Updates the page row from a fresh crawl. Returns True when the content changed."""
    now = datetime.now(timezone.utc)
    new_hash = _hash_markdown(markdown)
    # Legacy rows have no stored hash: derive it from the old markdown so an unchanged
    # page is NOT re-chunked / re-questioned / re-embedded on the first refresh run.
    old_hash = page.content_hash or (
        _hash_markdown(page.markdown_content) if page.markdown_content else None
    )

    page.last_scraped_at = now
    page.content_hash = new_hash
    page.status = PageProcessStatus.COMPLETED
    if new_hash == old_hash:
        return False

    page.markdown_content = markdown
    page.content_changed_at = now
    page.chunked_at = None  # forces re-chunk -> new chunks -> old points swept
    return True


def _register_failure(page: ScrapedPage, max_retries: int) -> None:
    page.retries += 1
    if page.retries < max_retries:
        page.status = PageProcessStatus.PENDING
    elif page.markdown_content:
        # A failed REFRESH must not destroy a previously good page; keep serving it.
        logger.warning(f"[Scraper] Refresh failed for {page.url}; keeping previous content.")
        page.status = PageProcessStatus.COMPLETED
    else:
        page.status = PageProcessStatus.FAILED


async def scraper_worker(web_id: int, is_discovery_done: asyncio.Event, max_retries: int = 3) -> int:
    total_scraped = 0
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        excluded_tags=["nav", "footer", "header", "script", "style", "noscript", "aside", "form"],
        exclude_external_links=True,
        exclude_social_media_links=True,
        page_timeout=35000,
        wait_until="domcontentloaded",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    )

    crawler = AsyncWebCrawler()
    await crawler.start()

    try:
        while True:
            async with async_session() as session:
                stmt = (
                    select(ScrapedPage)
                    .where(
                        ScrapedPage.web_id == web_id,
                        ScrapedPage.status == PageProcessStatus.PENDING,
                        ScrapedPage.retries < max_retries,
                    )
                    .limit(10)
                )
                res = await session.execute(stmt)
                pages = res.scalars().all()

                if not pages:
                    if is_discovery_done.is_set():
                        break
                    await asyncio.sleep(1.0)
                    continue

                for page in pages:
                    page.status = PageProcessStatus.IN_PROGRESS
                await session.commit()

                for page in pages:
                    try:
                        crawl_result = await crawler.arun(url=page.url, config=config)
                        if crawl_result.success and crawl_result.markdown:
                            _apply_scrape_result(page, str(crawl_result.markdown))
                            total_scraped += 1
                        else:
                            _register_failure(page, max_retries)
                    except Exception as e:
                        logger.warning(f"[Scraper Error] {page.url}: {e}")
                        _register_failure(page, max_retries)

                    # Polite pacing to avoid triggering Cloudflare / Nginx TCP reset triggers
                    await asyncio.sleep(1.0)

                await session.commit()
    finally:
        await crawler.close()

    return total_scraped


async def _has_pending_chunks_to_create(web_id: int) -> bool:
    async with async_session() as session:
        count = await session.scalar(
            select(func.count(ScrapedPage.id)).where(
                ScrapedPage.web_id == web_id,
                ScrapedPage.status == PageProcessStatus.COMPLETED,
                ScrapedPage.chunked_at.is_(None),
                ScrapedPage.markdown_content.is_not(None),
            )
        )
        return (count or 0) > 0


async def chunker_worker(web_id: int, is_scraping_done: asyncio.Event) -> int:
    total_chunks = 0
    while True:
        try:
            created = await process_and_chunk_pages(web_id=web_id, batch_size=20)
            if created > 0:
                total_chunks += created
                continue

            # If nothing was created, verify if upstream scraping has finished
            if is_scraping_done.is_set():
                if not await _has_pending_chunks_to_create(web_id):
                    break

            await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"[Chunker Worker Exception]: {e}")
            traceback.print_exc()
            await asyncio.sleep(2.0)

    return total_chunks


async def _has_pending_qgen_chunks(web_id: int) -> bool:
    async with async_session() as session:
        count = await session.scalar(
            select(func.count(Chunk.id))
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(
                ScrapedPage.web_id == web_id,
                Chunk.has_qgen.is_(False),
                Chunk.qgen_attempts < QGEN_MAX_ATTEMPTS,
            )
        )
        return (count or 0) > 0


async def qgen_worker(web_id: int, is_chunking_done: asyncio.Event) -> int:
    total_questions = 0
    generator = get_question_generator()
    CHUNK_BATCH_SIZE = 10

    while True:
        try:
            async with async_session() as session:
                stmt = (
                    select(
                        Chunk.id,
                        Chunk.content,
                        Chunk.heading_path,
                        ScrapedPage.org_id,
                        ScrapedPage.url.label("page_url"),
                    )
                    .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
                    .where(
                        ScrapedPage.web_id == web_id,
                        Chunk.has_qgen.is_(False),
                        Chunk.qgen_attempts < QGEN_MAX_ATTEMPTS,
                    )
                    .order_by(Chunk.id)
                    .limit(CHUNK_BATCH_SIZE)
                )
                rows = (await session.execute(stmt)).all()

                if not rows:
                    if is_chunking_done.is_set():
                        if not await _has_pending_qgen_chunks(web_id):
                            break
                    await asyncio.sleep(2.0)
                    continue

                chunk_ids = [r.id for r in rows]
                payloads: List[RawChunk] = []
                for r in rows:
                    tenant_str = str(r.org_id)
                    payloads.append(
                        RawChunk(
                            id=str(r.id),
                            doc_id=generate_doc_id(tenant_id=tenant_str, source_url=r.page_url),
                            source_url=r.page_url,
                            title=r.heading_path or r.page_url.split("/")[-1] or "Homepage",
                            content=r.content,
                            tags=[tenant_str],
                        )
                    )

                try:
                    generated_map = await generator.generate_questions_batch(payloads)

                    new_questions: List[GeneratedQuestion] = []
                    done_ids: List[int] = []
                    for p in payloads:
                        if p.id not in generated_map:
                            continue
                        done_ids.append(int(p.id))
                        for item in generated_map[p.id]:
                            q_text = (item.content if hasattr(item, "content") else str(item)).strip()
                            if q_text:
                                new_questions.append(
                                    GeneratedQuestion(
                                        chunk_id=int(p.id),
                                        question=q_text,
                                        is_synced_qdrant=False,
                                    )
                                )
                                total_questions += 1

                    if new_questions:
                        session.add_all(new_questions)
                    if done_ids:
                        await session.execute(
                            update(Chunk).where(Chunk.id.in_(done_ids)).values(has_qgen=True)
                        )
                    missed = [cid for cid in chunk_ids if cid not in done_ids]
                    if missed:
                        await session.execute(
                            update(Chunk)
                            .where(Chunk.id.in_(missed))
                            .values(qgen_attempts=Chunk.qgen_attempts + 1)
                        )
                    await session.commit()

                except Exception as e:
                    await session.rollback()
                    logger.error(f"[QGen Batch Error] chunks={chunk_ids}: {e}")
                    async with async_session() as err_sess:
                        await err_sess.execute(
                            update(Chunk)
                            .where(Chunk.id.in_(chunk_ids))
                            .values(qgen_attempts=Chunk.qgen_attempts + 1)
                        )
                        await err_sess.commit()

            await asyncio.sleep(4.0)
        except Exception as outer_e:
            logger.error(f"[QGen Worker Exception]: {outer_e}")
            traceback.print_exc()
            await asyncio.sleep(3.0)

    return total_questions


async def _has_pending_sync_questions(web_id: int) -> bool:
    sync_col = get_active_sync_column()
    async with async_session() as session:
        count = await session.scalar(
            select(func.count(GeneratedQuestion.id))
            .join(Chunk, GeneratedQuestion.chunk_id == Chunk.id)
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(
                ScrapedPage.web_id == web_id,
                sync_col.is_(False),
            )
        )
        return (count or 0) > 0


async def qdrant_sync_worker(org_id: int, web_id: int, is_qgen_done: asyncio.Event) -> int:
    total_synced = 0
    vector_db = get_vector_db()
    embedder = get_embedder()
    sparse_embedder = get_sparse_embedder()
    target_collection = settings.collection_name
    sync_col = get_active_sync_column()

    # Initializes Qdrant collection matching embedder dimensions (768)
    await vector_db.create_collection_if_not_exists(
        collection_name=target_collection,
        dense_vector_size=embedder.dimension,
        distance="Cosine",
        enable_quantization=settings.quantization_enabled,
    )

    tenant_key = str(org_id)
    # Pull 100 questions per batch to maximize API throughput and reduce cost
    EMBED_DB_BATCH_SIZE = 100
    consecutive_failures = 0

    while True:
        try:
            async with async_session() as session:
                stmt = (
                    select(
                        GeneratedQuestion.id.label("q_id"),
                        GeneratedQuestion.question.label("q_text"),
                        Chunk.id.label("chunk_id"),
                        Chunk.content.label("chunk_content"),
                        Chunk.chunk_index.label("chunk_index"),
                        Chunk.section_id.label("section_id"),
                        Chunk.heading_path.label("heading_path"),
                        Chunk.part_index.label("part_index"),
                        Chunk.part_total.label("part_total"),
                        ScrapedPage.id.label("page_id"),
                        ScrapedPage.url.label("page_url"),
                        ScrapedPage.doc_period.label("page_doc_period"),
                        ScrapedPage.content_changed_at.label("page_updated_at"),
                    )
                    .join(Chunk, GeneratedQuestion.chunk_id == Chunk.id)
                    .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
                    .where(
                        ScrapedPage.web_id == web_id,
                        sync_col.is_(False),
                    )
                    .order_by(GeneratedQuestion.id)
                    .limit(EMBED_DB_BATCH_SIZE)
                )
                rows = (await session.execute(stmt)).all()

                if not rows:
                    if is_qgen_done.is_set():
                        if not await _has_pending_sync_questions(web_id):
                            break
                    await asyncio.sleep(2.0)
                    continue

                try:
                    # Embeds all 100 questions in a single API batch call
                    embedded_results = await embedder.embed(
                        [r.q_text for r in rows], task_type="RETRIEVAL_DOCUMENT"
                    )
                    if len(embedded_results) != len(rows):
                        raise ValueError(
                            f"Embedding count mismatch: expected {len(rows)}, got {len(embedded_results)}"
                        )

                    chunk_sparse_cache: Dict[int, SparseVectorData] = {}
                    points_to_upsert: List[VectorPoint] = []
                    synced_q_ids: List[int] = []

                    for row, emb_res in zip(rows, embedded_results):
                        doc_type = classify_document_type(row.page_url, row.chunk_content)
                        campus = extract_sub_entity_from_url(row.page_url)
                        academic_level = classify_academic_level(row.page_url, row.chunk_content)
                        # chunk-level period wins (most specific), page-level is the fallback
                        doc_period = extract_doc_period(
                            row.chunk_content, url=row.page_url, heading=row.heading_path or ""
                        ) or row.page_doc_period

                        if row.chunk_id not in chunk_sparse_cache:
                            sparse_data = await sparse_embedder.embed_text(row.chunk_content)
                            if not sparse_data.indices:
                                sparse_data = SparseVectorData(indices=[0], values=[0.0])
                            chunk_sparse_cache[row.chunk_id] = sparse_data
                        sparse_data = chunk_sparse_cache[row.chunk_id]

                        chunk_uuid = generate_chunk_id(
                            tenant_id=tenant_key,
                            source_url=row.page_url,
                            chunk_index=row.chunk_id,
                            content=row.chunk_content,
                        )
                        point_uuid = generate_question_id(chunk_id=chunk_uuid, question=row.q_text)

                        points_to_upsert.append(
                            VectorPoint(
                                id=point_uuid,
                                vector={
                                    "question_dense": emb_res.values,
                                    "chunk_sparse": sparse_data,
                                },
                                payload={
                                    "group_id": tenant_key,
                                    "web_id": web_id,
                                    "parent_chunk_id": chunk_uuid,
                                    "question_text": row.q_text,
                                    "chunk_text": row.chunk_content,
                                    "source_url": row.page_url,
                                    "page_id": row.page_id,
                                    "chunk_id": row.chunk_id,
                                    "chunk_index": row.chunk_index,
                                    "section_id": row.section_id,
                                    "heading_path": row.heading_path,
                                    "part_index": row.part_index,
                                    "part_total": row.part_total,
                                    "doc_type": doc_type,
                                    "campus": campus,
                                    "academic_level": academic_level,
                                    "doc_period": doc_period,
                                    "page_updated_at": (
                                        row.page_updated_at.isoformat()
                                        if row.page_updated_at else None
                                    ),
                                },
                            )
                        )
                        synced_q_ids.append(row.q_id)

                    await vector_db.upsert_points(
                        collection_name=target_collection, points=points_to_upsert
                    )

                    # Dynamically updates active model sync flag and legacy flag
                    await session.execute(
                        update(GeneratedQuestion)
                        .where(GeneratedQuestion.id.in_(synced_q_ids))
                        .values({
                            sync_col.key: True,
                            GeneratedQuestion.is_synced_qdrant: True,
                        })
                    )
                    await session.commit()
                    total_synced += len(points_to_upsert)
                    consecutive_failures = 0

                    # Standard pacing on paid tier to avoid network bursts
                    await asyncio.sleep(0.5)

                except Exception as e:
                    await session.rollback()
                    consecutive_failures += 1
                    err_msg = str(e)
                    logger.error(
                        f"[Qdrant Sync Error] attempt {consecutive_failures}: {err_msg[:200]}"
                    )
                    traceback.print_exc()

                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        logger.warning(
                            "[Qdrant Sync Rate Limit] Quota hit. Sleeping 15s before retrying batch..."
                        )
                        await asyncio.sleep(15.0)
                        consecutive_failures = 0
                    elif consecutive_failures >= SYNC_MAX_CONSECUTIVE_FAILURES:
                        logger.warning(
                            "[Qdrant Sync Backoff] Consecutive errors reached threshold. Sleeping 10s..."
                        )
                        await asyncio.sleep(10.0)
                        consecutive_failures = 0
                    else:
                        await asyncio.sleep(3.0)

        except Exception as loop_e:
            logger.error(f"[Qdrant Sync Worker Loop Exception]: {loop_e}")
            traceback.print_exc()
            await asyncio.sleep(5.0)

    return total_synced


# --------------------------------------------------------------------------- #
# Post-pipeline reconciliation (stale data removal)
# --------------------------------------------------------------------------- #
async def reconcile_stale_points(org_id: int, web_id: int) -> int:
    """
    Deletes Qdrant points of re-chunked pages whose chunk_id no longer exists
    (orphans from previous versions of the page). Runs only after a clean pipeline
    so the new points are already in place. Checkpointed via qdrant_cleanup_pending,
    so it is idempotent and safe to retry.
    """
    async with async_session() as session:
        page_ids = list(
            (
                await session.execute(
                    select(ScrapedPage.id).where(
                        ScrapedPage.web_id == web_id,
                        ScrapedPage.qdrant_cleanup_pending.is_(True),
                    )
                )
            ).scalars().all()
        )
    if not page_ids:
        return 0

    vector_db = get_vector_db()
    try:
        for page_id in page_ids:
            async with async_session() as session:
                live_chunk_ids = list(
                    (
                        await session.execute(select(Chunk.id).where(Chunk.page_id == page_id))
                    ).scalars().all()
                )
            await vector_db.delete_points(
                collection_name=settings.collection_name,
                filters={"group_id": str(org_id), "page_id": page_id},
                must_not={"chunk_id": live_chunk_ids} if live_chunk_ids else None,
            )
            async with async_session() as session:
                await session.execute(
                    update(ScrapedPage)
                    .where(ScrapedPage.id == page_id)
                    .values(qdrant_cleanup_pending=False)
                )
                await session.commit()
    finally:
        await vector_db.close()

    logger.info(f"[Reconcile] Swept stale Qdrant points for {len(page_ids)} pages (web {web_id}).")
    return len(page_ids)


async def purge_missing_pages(
    org_id: int, web_id: int, run_started_at: datetime, discovered_count: int
) -> int:
    """
    Removes pages (Qdrant points + Postgres rows) that a successful discovery no longer
    lists, i.e. pages deleted from the website. Skipped when discovery looks degraded.
    """
    async with async_session() as session:
        total = await session.scalar(
            select(func.count(ScrapedPage.id)).where(ScrapedPage.web_id == web_id)
        ) or 0
        stale_ids = list(
            (
                await session.execute(
                    select(ScrapedPage.id).where(
                        ScrapedPage.web_id == web_id,
                        or_(
                            ScrapedPage.last_seen_at.is_(None),
                            ScrapedPage.last_seen_at < run_started_at,
                        ),
                    )
                )
            ).scalars().all()
        )

    if not stale_ids:
        return 0
    if discovered_count <= 0 or len(stale_ids) > PURGE_MAX_FRACTION * max(total, 1):
        logger.warning(
            f"[Purge] Skipped for web {web_id}: {len(stale_ids)}/{total} pages missing, "
            f"{discovered_count} discovered (guard tripped)."
        )
        return 0

    vector_db = get_vector_db()
    try:
        for page_id in stale_ids:
            await vector_db.delete_points(
                collection_name=settings.collection_name,
                filters={"group_id": str(org_id), "page_id": page_id},
            )
    finally:
        await vector_db.close()

    async with async_session() as session:
        # chunks / generated_questions go away through the FK ON DELETE CASCADE
        await session.execute(delete(ScrapedPage).where(ScrapedPage.id.in_(stale_ids)))
        await session.commit()

    logger.info(f"[Purge] Removed {len(stale_ids)} pages no longer present on web {web_id}.")
    return len(stale_ids)


async def _bump_content_version(org_id: int) -> None:
    async with async_session() as session:
        await session.execute(
            update(Org).where(Org.id == org_id).values(content_version=Org.content_version + 1)
        )
        await session.commit()


async def run_full_pipeline(
    website_id: int,
    refresh_after_hours: Optional[float] = DEFAULT_REFRESH_AFTER_HOURS,
) -> dict:
    run_started_at = datetime.now(timezone.utc)

    async with async_session() as session:
        website = await session.get(Website, website_id)
        if not website:
            raise ValueError(f"Website with id {website_id} not found")

        website.status = WebsiteScrapeStatus.IN_PROGRESS
        website.error_message = None

        # Reclaim pages stranded IN_PROGRESS by any previous crash
        await session.execute(
            update(ScrapedPage)
            .where(
                ScrapedPage.web_id == website_id,
                ScrapedPage.status == PageProcessStatus.IN_PROGRESS,
            )
            .values(status=PageProcessStatus.PENDING)
        )

        # Re-queue stale pages (and previously FAILED ones) so site edits are picked up.
        # Old markdown/chunks stay in place until a changed version actually replaces them.
        if refresh_after_hours is not None:
            cutoff = run_started_at - timedelta(hours=refresh_after_hours)
            await session.execute(
                update(ScrapedPage)
                .where(
                    ScrapedPage.web_id == website_id,
                    ScrapedPage.status.in_(
                        [PageProcessStatus.COMPLETED, PageProcessStatus.FAILED]
                    ),
                    or_(
                        ScrapedPage.last_scraped_at.is_(None),
                        ScrapedPage.last_scraped_at < cutoff,
                    ),
                )
                .values(status=PageProcessStatus.PENDING, retries=0)
            )
        await session.commit()

        org_id = website.org_id
        base_url = website.url

    is_discovery_done = asyncio.Event()
    is_scraping_done = asyncio.Event()
    is_chunking_done = asyncio.Event()
    is_qgen_done = asyncio.Event()

    async def _discovery_task():
        try:
            return await run_discovery(org_id=org_id, web_id=website_id, base_url=base_url)
        except Exception as e:
            logger.error(f"Discovery stage failed: {e}")
            raise
        finally:
            is_discovery_done.set()

    async def _scraper_task():
        try:
            return await scraper_worker(web_id=website_id, is_discovery_done=is_discovery_done)
        except Exception as e:
            logger.error(f"Scraper stage failed: {e}")
            raise
        finally:
            is_scraping_done.set()

    async def _chunker_task():
        try:
            return await chunker_worker(web_id=website_id, is_scraping_done=is_scraping_done)
        except Exception as e:
            logger.error(f"Chunker stage failed: {e}")
            raise
        finally:
            is_chunking_done.set()

    async def _qgen_task():
        try:
            return await qgen_worker(web_id=website_id, is_chunking_done=is_chunking_done)
        except Exception as e:
            logger.error(f"QGen stage failed: {e}")
            raise
        finally:
            is_qgen_done.set()

    async def _sync_task():
        try:
            return await qdrant_sync_worker(org_id=org_id, web_id=website_id, is_qgen_done=is_qgen_done)
        except Exception as e:
            logger.error(f"Qdrant Sync stage failed: {e}")
            raise

    results = await asyncio.gather(
        _discovery_task(),
        _scraper_task(),
        _chunker_task(),
        _qgen_task(),
        _sync_task(),
        return_exceptions=True,
    )

    errors = [r for r in results if isinstance(r, BaseException)]

    def _num(v) -> int:
        return v if isinstance(v, int) else 0

    # Stale-data reconciliation only after a clean run (new points are guaranteed in place).
    cleaned_pages = purged_pages = 0
    if not errors:
        try:
            cleaned_pages = await reconcile_stale_points(org_id, website_id)
            purged_pages = await purge_missing_pages(
                org_id, website_id, run_started_at, discovered_count=_num(results[0])
            )
        except Exception as e:
            logger.error(f"Reconciliation failed for website {website_id}: {e}")
            traceback.print_exc()
            errors.append(e)

    # Invalidate semantic-cache entries of this tenant if anything indexed changed.
    if _num(results[2]) > 0 or cleaned_pages > 0 or purged_pages > 0:
        try:
            await _bump_content_version(org_id)
        except Exception as e:
            logger.error(f"Failed to bump content_version for org {org_id}: {e}")

    async with async_session() as session:
        website = await session.get(Website, website_id)
        if website:
            if errors:
                website.status = WebsiteScrapeStatus.FAILED
                err_strings = [f"{type(e).__name__}: {e}" for e in errors]
                website.error_message = "; ".join(err_strings)[:2000]
                logger.error(f"Ingestion pipeline failed for website {website_id}: {website.error_message}")
            else:
                website.status = WebsiteScrapeStatus.COMPLETED
                website.error_message = None
            await session.commit()

    if errors:
        raise errors[0]

    discovered_urls, scraped_pages, created_chunks, generated_questions, synced_qdrant_points = results
    return {
        "discovered_urls": discovered_urls,
        "scraped_pages": scraped_pages,
        "created_chunks": created_chunks,
        "generated_questions": generated_questions,
        "synced_qdrant_points": synced_qdrant_points,
        "swept_pages": cleaned_pages,
        "purged_pages": purged_pages,
    }