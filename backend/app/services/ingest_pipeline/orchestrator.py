import asyncio
from datetime import datetime, timezone
import math
import re
import traceback
from typing import Dict, List
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from sqlalchemy import select, update, delete

from app.core.config import settings
from app.core.database import async_session
from app.models.chunk import Chunk
from app.models.generated_question import GeneratedQuestion
from app.models.scraped_page import PageProcessStatus, ScrapedPage
from app.models.website import Website, WebsiteScrapeStatus
from app.services.embeddings.factory import get_embedder
from app.services.embeddings.sparse_embedder import get_sparse_embedder
from app.services.ingest_pipeline.clean_markdown import clean_markdown
from app.services.ingest_pipeline.discovery import run_discovery
from app.services.llm_qgen.factory import get_question_generator
from app.services.llm_qgen.schema import RawChunk
from app.services.vector_db.factory import get_vector_db
from app.services.vector_db.schema import SparseVectorData, VectorPoint
from app.utils.uuid_generator import generate_chunk_id, generate_doc_id, generate_question_id


def estimate_token_count(text: str) -> int:
    return max(1, len(text.split()))


def classify_document_type(url: str, text: str = "") -> str:
    path = urlparse(url).path.lower()
    ephemeral_indicators = [
        "/news", "/announcement", "/announcements",
        "/events", "/event", "/blog", "/posts", "/press",
        "/memorandum", "/advisory", "/bulletin"
    ]
    if any(token in path for token in ephemeral_indicators):
        return "ephemeral"

    if re.search(r"/(?:19|20)\d{2}/", path):
        return "ephemeral"

    lower_content = text[:600].lower()
    if re.search(r"a\.?y\.?\s*20(?:1\d|2[0-4])", lower_content):
        return "ephemeral"

    return "evergreen"


def is_substantive_chunk(text: str) -> bool:
    words = text.split()
    if len(words) < 15:
        return False

    boilerplate_indicators = [
        "cookie", "privacy policy", "terms of use", "all rights reserved",
        "share on facebook", "share on x", "share on linkedin",
        "agree decline", "_chevron_right_", "navigation", "explore our website",
        "skip to content", "back to top", "read more", "click here",
        "related stories", "featured articles", "trending news", "leave a reply"
    ]
    lower_text = text.lower()
    matches = sum(1 for indicator in boilerplate_indicators if indicator in lower_text)
    if matches >= 2:
        return False

    symbols_count = len(re.findall(r"[_*\[\]\(\)!|#<>]", text))
    if symbols_count / max(1, len(text)) > 0.25:
        return False

    sentences = [s for s in re.split(r"[.!?\n]+", text) if len(s.strip().split()) >= 3]
    if len(sentences) < 1:
        return False

    return True


async def scraper_worker(web_id: int, is_discovery_done: asyncio.Event, max_retries: int = 3) -> int:
    total_scraped = 0
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        excluded_tags=[
            "nav", "footer", "header", "script", "style", "noscript",
            "aside", "form"
        ],
        exclude_external_links=True,
        exclude_social_media_links=True,
        page_timeout=25000,
        wait_until="commit",
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
                    except Exception:
                        page.retries += 1
                        page.status = (
                            PageProcessStatus.FAILED
                            if page.retries >= max_retries
                            else PageProcessStatus.PENDING
                        )

                await session.commit()
    finally:
        await crawler.close()

    return total_scraped


async def chunker_worker(
    web_id: int,
    is_scraping_done: asyncio.Event,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> int:
    total_chunks = 0

    headers_to_split_on = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
        ("####", "Header 4"),
    ]
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on,
        strip_headers=False,
    )

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    while True:
        async with async_session() as session:
            stmt = (
                select(ScrapedPage)
                .where(
                    ScrapedPage.web_id == web_id,
                    ScrapedPage.status == PageProcessStatus.COMPLETED,
                    ScrapedPage.chunked_at.is_(None),
                    ScrapedPage.markdown_content.is_not(None),
                )
                .limit(20)
            )
            res = await session.execute(stmt)
            pages = res.scalars().all()

            if not pages:
                if is_scraping_done.is_set():
                    break
                await asyncio.sleep(1.0)
                continue

            for page in pages:
                cleaned = clean_markdown(page.markdown_content or "")
                if cleaned.startswith("---"):
                    parts = cleaned.split("---", 2)
                    if len(parts) >= 3:
                        cleaned = parts[2].strip()

                header_docs = header_splitter.split_text(cleaned)
                sections = header_docs if header_docs else [Document(page_content=cleaned)]
                valid_chunks: List[Chunk] = []

                for sec in sections:
                    split_texts = text_splitter.split_text(sec.page_content)
                    for text in split_texts:
                        stripped = text.strip()
                        if is_substantive_chunk(stripped):
                            valid_chunks.append(
                                Chunk(
                                    page_id=page.id,
                                    content=stripped,
                                    token_count=estimate_token_count(stripped),
                                    has_qgen=False,
                                )
                            )

                await session.execute(delete(Chunk).where(Chunk.page_id == page.id))
                if valid_chunks:
                    session.add_all(valid_chunks)
                    total_chunks += len(valid_chunks)

                page.chunked_at = datetime.now(timezone.utc)

            await session.commit()

    return total_chunks


async def qgen_worker(web_id: int, is_chunking_done: asyncio.Event) -> int:
    total_questions = 0
    generator = get_question_generator()
    CHUNK_BATCH_SIZE = 10

    while True:
        async with async_session() as session:
            stmt = (
                select(
                    Chunk.id,
                    Chunk.content,
                    ScrapedPage.id.label("page_id"),
                    ScrapedPage.org_id,
                    ScrapedPage.url.label("page_url"),
                )
                .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
                .where(
                    ScrapedPage.web_id == web_id,
                    Chunk.has_qgen.is_(False),
                )
                .limit(CHUNK_BATCH_SIZE)
            )
            res = await session.execute(stmt)
            rows = res.all()

            if not rows:
                if is_chunking_done.is_set():
                    break
                await asyncio.sleep(2.0)
                continue

            chunk_ids = [r[0] for r in rows]
            raw_chunk_payloads: List[RawChunk] = []

            for chunk_id, chunk_content, page_id, page_org_id, page_url in rows:
                tenant_str = str(page_org_id)
                doc_id = generate_doc_id(tenant_id=tenant_str, source_url=page_url)
                raw_chunk_payloads.append(
                    RawChunk(
                        id=str(chunk_id),
                        doc_id=doc_id,
                        source_url=page_url,
                        title=page_url.split("/")[-1] or "Homepage",
                        content=chunk_content,
                        tags=[tenant_str],
                    )
                )

            try:
                generated_map = await generator.generate_questions_batch(raw_chunk_payloads)
                new_questions = []

                for chunk_payload in raw_chunk_payloads:
                    q_list = generated_map.get(chunk_payload.id, [])
                    for item in q_list:
                        q_text = item.content if hasattr(item, "content") else str(item)
                        if q_text.strip():
                            new_questions.append(
                                GeneratedQuestion(
                                    chunk_id=int(chunk_payload.id),
                                    question=q_text.strip(),
                                    is_synced_qdrant=False,
                                )
                            )
                            total_questions += 1

                if new_questions:
                    session.add_all(new_questions)

                await session.execute(
                    update(Chunk).where(Chunk.id.in_(chunk_ids)).values(has_qgen=True)
                )
                await session.commit()

            except Exception as e:
                await session.rollback()
                print(f"[QGen Batch Error] chunks={chunk_ids}: {e}")
                async with async_session() as err_sess:
                    await err_sess.execute(
                        update(Chunk).where(Chunk.id.in_(chunk_ids)).values(has_qgen=True)
                    )
                    await err_sess.commit()

            await asyncio.sleep(4.0)

    return total_questions


async def qdrant_sync_worker(org_id: int, web_id: int, is_qgen_done: asyncio.Event) -> int:
    total_synced = 0
    vector_db = get_vector_db()
    embedder = get_embedder()
    sparse_embedder = get_sparse_embedder()
    target_collection = settings.collection_name

    try:
        await vector_db.create_collection_if_not_exists(
            collection_name=target_collection,
            dense_vector_size=embedder.dimension,
            distance="Cosine",
            enable_quantization=settings.quantization_enabled,
        )
    except Exception as e:
        print(f"[Qdrant Sync Init Notice]: {e}")

    tenant_key = str(org_id)
    EMBED_DB_BATCH_SIZE = 50

    while True:
        async with async_session() as session:
            stmt = (
                select(
                    GeneratedQuestion.id.label("q_id"),
                    GeneratedQuestion.question.label("q_text"),
                    Chunk.id.label("chunk_id"),
                    Chunk.content.label("chunk_content"),
                    ScrapedPage.id.label("page_id"),
                    ScrapedPage.url.label("page_url"),
                )
                .join(Chunk, GeneratedQuestion.chunk_id == Chunk.id)
                .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
                .where(
                    ScrapedPage.web_id == web_id,
                    GeneratedQuestion.is_synced_qdrant.is_(False),
                )
                .limit(EMBED_DB_BATCH_SIZE)
            )
            res = await session.execute(stmt)
            rows = res.all()

            if not rows:
                if is_qgen_done.is_set():
                    break
                await asyncio.sleep(2.0)
                continue

            question_texts = [r.q_text for r in rows]

            try:
                print(f"[Qdrant Sync] Embedding batch of {len(question_texts)} questions...")
                embedded_results = await embedder.embed(
                    question_texts, task_type="RETRIEVAL_DOCUMENT"
                )

                if len(embedded_results) != len(rows):
                    raise ValueError(
                        f"Embedding count mismatch: expected {len(rows)}, got {len(embedded_results)}"
                    )

                chunk_sparse_cache: Dict[int, SparseVectorData] = {}
                points_to_upsert: List[VectorPoint] = []
                synced_q_ids: List[int] = []

                for row, emb_res in zip(rows, embedded_results):
                    q_id = row.q_id
                    q_text = row.q_text
                    chunk_id = row.chunk_id
                    chunk_content = row.chunk_content
                    page_id = row.page_id
                    page_url = row.page_url

                    doc_type = classify_document_type(page_url, chunk_content)

                    if chunk_id not in chunk_sparse_cache:
                        sparse_data = await sparse_embedder.embed_text(chunk_content)
                        if not sparse_data.indices:
                            sparse_data = SparseVectorData(indices=[0], values=[0.0])
                        chunk_sparse_cache[chunk_id] = sparse_data

                    sparse_data = chunk_sparse_cache[chunk_id]

                    chunk_uuid = generate_chunk_id(
                        tenant_id=tenant_key,
                        source_url=page_url,
                        chunk_index=chunk_id,
                        content=chunk_content,
                    )
                    point_uuid = generate_question_id(
                        chunk_id=chunk_uuid,
                        question=q_text,
                    )

                    point = VectorPoint(
                        id=point_uuid,
                        vector={
                            "question_dense": emb_res.values,
                            "chunk_sparse": sparse_data,
                        },
                        payload={
                            "group_id": tenant_key,
                            "parent_chunk_id": chunk_uuid,
                            "question_text": q_text,
                            "chunk_text": chunk_content,
                            "source_url": page_url,
                            "page_id": page_id,
                            "chunk_id": chunk_id,
                            "doc_type": doc_type,
                        },
                    )
                    points_to_upsert.append(point)
                    synced_q_ids.append(q_id)

                if points_to_upsert:
                    print(f"[Qdrant Sync] Upserting {len(points_to_upsert)} points to {target_collection}...")
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
                    print(f"[Qdrant Sync] Synced {len(points_to_upsert)} points. (Cumulative: {total_synced})")

            except Exception as e:
                await session.rollback()
                print(f"[Qdrant Sync Error] Failed on batch: {e}")
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
        finally:
            is_discovery_done.set()

    async def _scraper_task():
        try:
            return await scraper_worker(web_id=website_id, is_discovery_done=is_discovery_done)
        finally:
            is_scraping_done.set()

    async def _chunker_task():
        try:
            return await chunker_worker(web_id=website_id, is_scraping_done=is_scraping_done)
        finally:
            is_chunking_done.set()

    async def _qgen_task():
        try:
            return await qgen_worker(web_id=website_id, is_chunking_done=is_chunking_done)
        finally:
            is_qgen_done.set()

    (
        discovered_urls,
        scraped_pages,
        created_chunks,
        generated_questions,
        synced_qdrant_points,
    ) = await asyncio.gather(
        _discovery_task(),
        _scraper_task(),
        _chunker_task(),
        _qgen_task(),
        qdrant_sync_worker(org_id=org_id, web_id=website_id, is_qgen_done=is_qgen_done),
    )

    async with async_session() as session:
        website = await session.get(Website, website_id)
        if website:
            website.status = WebsiteScrapeStatus.COMPLETED
            await session.commit()

    return {
        "discovered_urls": discovered_urls,
        "scraped_pages": scraped_pages,
        "created_chunks": created_chunks,
        "generated_questions": generated_questions,
        "synced_qdrant_points": synced_qdrant_points,
    }