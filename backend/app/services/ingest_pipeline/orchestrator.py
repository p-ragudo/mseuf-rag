import asyncio
import logging
import re
import traceback
from datetime import datetime
from typing import Dict, List
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from sqlalchemy import select, update, func

from app.core.config import settings
from app.core.database import async_session
from app.models.chunk import Chunk
from app.models.generated_question import GeneratedQuestion
from app.models.scraped_page import PageProcessStatus, ScrapedPage
from app.models.website import Website, WebsiteScrapeStatus
from app.services.embeddings.factory import get_embedder
from app.services.embeddings.sparse_embedder import get_sparse_embedder
from app.services.ingest_pipeline.chunk import process_and_chunk_pages
from app.services.ingest_pipeline.chunker import (  # noqa: F401
    estimate_token_count,
    is_substantive_chunk,
)
from app.services.ingest_pipeline.discovery import run_discovery
from app.services.llm_qgen.factory import get_question_generator
from app.services.llm_qgen.schema import RawChunk
from app.services.vector_db.factory import get_vector_db
from app.services.vector_db.schema import SparseVectorData, VectorPoint
from app.utils.uuid_generator import generate_chunk_id, generate_doc_id, generate_question_id

logger = logging.getLogger(__name__)

QGEN_MAX_ATTEMPTS = 3
SYNC_MAX_CONSECUTIVE_FAILURES = 5


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
                            page.markdown_content = crawl_result.markdown
                            page.status = PageProcessStatus.COMPLETED
                            total_scraped += 1
                        else:
                            page.retries += 1
                            page.status = (
                                PageProcessStatus.FAILED
                                if page.retries >= max_retries
                                else PageProcessStatus.PENDING
                            )
                    except Exception as e:
                        logger.warning(f"[Scraper Error] {page.url}: {e}")
                        page.retries += 1
                        page.status = (
                            PageProcessStatus.FAILED
                            if page.retries >= max_retries
                            else PageProcessStatus.PENDING
                        )
                    
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
    async with async_session() as session:
        count = await session.scalar(
            select(func.count(GeneratedQuestion.id))
            .join(Chunk, GeneratedQuestion.chunk_id == Chunk.id)
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(
                ScrapedPage.web_id == web_id,
                GeneratedQuestion.is_synced_qdrant.is_(False),
            )
        )
        return (count or 0) > 0


async def qdrant_sync_worker(org_id: int, web_id: int, is_qgen_done: asyncio.Event) -> int:
    total_synced = 0
    vector_db = get_vector_db()
    embedder = get_embedder()
    sparse_embedder = get_sparse_embedder()
    target_collection = settings.collection_name

    await vector_db.create_collection_if_not_exists(
        collection_name=target_collection,
        dense_vector_size=embedder.dimension,
        distance="Cosine",
        enable_quantization=settings.quantization_enabled,
    )

    tenant_key = str(org_id)
    # Pull 100 questions at a time to match embedder BATCH_SIZE
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
                    )
                    .join(Chunk, GeneratedQuestion.chunk_id == Chunk.id)
                    .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
                    .where(
                        ScrapedPage.web_id == web_id,
                        GeneratedQuestion.is_synced_qdrant.is_(False),
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
                                },
                            )
                        )
                        synced_q_ids.append(row.q_id)

                    await vector_db.upsert_points(
                        collection_name=target_collection, points=points_to_upsert
                    )
                    await session.execute(
                        update(GeneratedQuestion)
                        .where(GeneratedQuestion.id.in_(synced_q_ids))
                        .values(is_synced_qdrant=True)
                    )
                    await session.commit()
                    total_synced += len(points_to_upsert)
                    consecutive_failures = 0

                    # Pacing delay: avoid bursting past Gemini free-tier RPM limits
                    await asyncio.sleep(2.0)

                except Exception as e:
                    await session.rollback()
                    consecutive_failures += 1
                    err_msg = str(e)
                    logger.error(
                        f"[Qdrant Sync Error] attempt {consecutive_failures}: {err_msg[:200]}"
                    )
                    traceback.print_exc()

                    # Never crash the worker. Back off and wait for quota/rate limits to recover.
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        logger.warning(
                            "[Qdrant Sync Rate Limit] Quota hit. Sleeping 30s before retrying batch..."
                        )
                        await asyncio.sleep(30.0)
                        consecutive_failures = 0
                    elif consecutive_failures >= SYNC_MAX_CONSECUTIVE_FAILURES:
                        logger.warning(
                            "[Qdrant Sync Backoff] Consecutive errors reached threshold. Sleeping 15s..."
                        )
                        await asyncio.sleep(15.0)
                        consecutive_failures = 0
                    else:
                        await asyncio.sleep(4.0)

        except Exception as loop_e:
            logger.error(f"[Qdrant Sync Worker Loop Exception]: {loop_e}")
            traceback.print_exc()
            await asyncio.sleep(5.0)

    return total_synced


async def run_full_pipeline(website_id: int) -> dict:
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
    }