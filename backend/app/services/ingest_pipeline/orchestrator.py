import asyncio
import hashlib
from collections import Counter
from datetime import datetime, timezone
import math
import re
from typing import Dict, List
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import selectinload, joinedload

from app.core.config import settings
from app.core.database import async_session
from app.models.chunk import Chunk
from app.models.generated_question import GeneratedQuestion
from app.models.scraped_page import PageProcessStatus, ScrapedPage
from app.models.website import Website, WebsiteScrapeStatus
from app.services.embeddings.factory import get_embedder
from app.services.ingest_pipeline.clean_markdown import clean_markdown
from app.services.ingest_pipeline.discovery import run_discovery
from app.services.llm_qgen.factory import get_question_generator
from app.services.llm_qgen.schema import RawChunk
from app.services.vector_db.factory import get_vector_db
from app.services.vector_db.schema import SparseVectorData, VectorPoint
from app.utils.uuid_generator import generate_chunk_id, generate_doc_id, generate_question_id

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can't", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's",
    "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than",
    "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there",
    "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't",
    "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's",
    "when", "when's", "where", "where's", "which", "while", "who", "who's", "whom",
    "why", "why's", "with", "won't", "would", "wouldn't", "you", "you'd", "you'll",
    "you're", "you've", "your", "yours", "yourself", "yourselves"
}


def estimate_token_count(text: str) -> int:
    return max(1, len(text.split()))


def classify_document_type(url: str, text: str = "") -> str:
    """
    Classifies content into 'ephemeral' or 'evergreen' based on URL path tokens,
    archive patterns, and past academic year mentions.
    """
    path = urlparse(url).path.lower()
    ephemeral_indicators = [
        "/news", "/announcement", "/announcements",
        "/events", "/event", "/blog", "/posts", "/press",
        "/memorandum", "/advisory", "/bulletin"
    ]
    if any(token in path for token in ephemeral_indicators):
        return "ephemeral"

    # Match past dates or years in path (e.g. /2021/, /2022/, /2023/, /2024/)
    if re.search(r"/(?:19|20)\d{2}/", path):
        return "ephemeral"

    # Flag older academic years if mentioned as past archives
    lower_content = text[:600].lower()
    if re.search(r"a\.?y\.?\s*20(?:1\d|2[0-4])", lower_content):
        return "ephemeral"

    return "evergreen"


def is_substantive_chunk(text: str) -> bool:
    """
    Filters out UI fragments, link directories, cookie policies, 
    and chunks with low information density.
    """
    words = text.split()
    if len(words) < 30:
        return False

    boilerplate_indicators = [
        "cookie", "privacy policy", "terms of use", "all rights reserved",
        "share on facebook", "share on x", "share on linkedin",
        "agree decline", "_chevron_right_", "navigation", "explore our website",
        "skip to content", "back to top", "read more", "click here"
    ]
    lower_text = text.lower()
    matches = sum(1 for indicator in boilerplate_indicators if indicator in lower_text)
    if matches >= 2:
        return False

    # Check for excessive markdown markup or punctuation clutter
    symbols_count = len(re.findall(r"[_*\[\]\(\)!|#<>]", text))
    if symbols_count / max(1, len(text)) > 0.20:
        return False

    # Ensure chunk contains at least two complete sentences
    sentences = [s for s in re.split(r"[.!?]+", text) if len(s.strip().split()) >= 4]
    if len(sentences) < 2:
        return False

    return True


def compute_simple_sparse_vector(text: str) -> SparseVectorData:
    """Generates stopword-filtered, log-scaled sparse frequency vectors."""
    raw_tokens = [w.lower() for w in re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", text)]
    filtered_tokens = [t for t in raw_tokens if t not in STOP_WORDS]
    if not filtered_tokens:
        return SparseVectorData(indices=[], values=[])

    counts = Counter(filtered_tokens)
    indices = []
    values = []

    for word, freq in counts.items():
        idx = int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16)
        indices.append(idx)
        # Apply sublinear TF scaling to prevent dominant repetition
        values.append(float(1.0 + math.log(freq)))

    sorted_pairs = sorted(zip(indices, values), key=lambda x: x[0])
    return SparseVectorData(
        indices=[p[0] for p in sorted_pairs],
        values=[p[1] for p in sorted_pairs],
    )


async def scraper_worker(web_id: int, is_discovery_done: asyncio.Event, max_retries: int = 3) -> int:
    total_scraped = 0
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        excluded_tags=["nav", "footer", "header", "script", "style", "noscript", "aside"],
        page_timeout=25000,
        wait_until="commit",
    )

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

            try:
                async with AsyncWebCrawler() as crawler:
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
            except Exception:
                for page in pages:
                    if page.status == PageProcessStatus.IN_PROGRESS:
                        page.retries += 1
                        page.status = (
                            PageProcessStatus.FAILED
                            if page.retries >= max_retries
                            else PageProcessStatus.PENDING
                        )

            await session.commit()

    return total_scraped


async def chunker_worker(
    web_id: int,
    is_scraping_done: asyncio.Event,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> int:
    total_chunks = 0
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

                split_texts = text_splitter.split_text(cleaned)
                valid_chunks: List[Chunk] = []

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
    """Generates synthetic questions for substantive chunks without ORM relationship lazy-loading."""
    total_questions = 0
    generator = get_question_generator()

    while True:
        async with async_session() as session:
            # Query plain scalars instead of ORM objects to prevent lazy loading
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
                .limit(5)
            )
            res = await session.execute(stmt)
            rows = res.all()

            if not rows:
                if is_chunking_done.is_set():
                    break
                await asyncio.sleep(2.0)
                continue

            for chunk_id, chunk_content, page_id, page_org_id, page_url in rows:
                tenant_str = str(page_org_id)
                doc_id = generate_doc_id(tenant_id=tenant_str, source_url=page_url)

                raw_chunk_payload = RawChunk(
                    id=str(chunk_id),
                    doc_id=doc_id,
                    source_url=page_url,
                    title=page_url.split("/")[-1] or "Homepage",
                    content=chunk_content,
                    tags=[tenant_str],
                )

                try:
                    generated = await generator.generate_questions(raw_chunk_payload)
                    new_questions = []
                    for item in generated:
                        q_text = item.content if hasattr(item, "content") else str(item)
                        if q_text.strip():
                            new_questions.append(
                                GeneratedQuestion(
                                    chunk_id=chunk_id,
                                    question=q_text.strip(),
                                    is_synced_qdrant=False,
                                )
                            )
                            total_questions += 1

                    if new_questions:
                        session.add_all(new_questions)

                    await session.execute(
                        update(Chunk).where(Chunk.id == chunk_id).values(has_qgen=True)
                    )
                    await session.commit()
                except Exception as e:
                    await session.rollback()
                    print(f"[QGen Error] chunk_id={chunk_id}: {e}")
                    async with async_session() as err_sess:
                        await err_sess.execute(
                            update(Chunk).where(Chunk.id == chunk_id).values(has_qgen=True)
                        )
                        await err_sess.commit()

                await asyncio.sleep(4.5)

    return total_questions


async def qdrant_sync_worker(org_id: int, web_id: int, is_qgen_done: asyncio.Event) -> int:
    """Batches generated questions, embeds them, and syncs points to Qdrant without ORM lazy-loading."""
    total_synced = 0
    vector_db = get_vector_db()
    embedder = get_embedder()
    target_collection = settings.collection_name

    await vector_db.create_collection_if_not_exists(
        collection_name=target_collection,
        dense_vector_size=embedder.dimension,
        distance="Cosine",
    )

    tenant_key = str(org_id)

    while True:
        async with async_session() as session:
            # Query plain primitive columns: eliminates all ORM relationship proxy overhead
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
                .limit(25)
            )
            res = await session.execute(stmt)
            rows = res.all()

            if not rows:
                if is_qgen_done.is_set():
                    break
                await asyncio.sleep(1.0)
                continue

            question_texts = [r.q_text for r in rows]
            embedded_results = embedder.embed(
                question_texts, task_type="RETRIEVAL_DOCUMENT"
            )
            await asyncio.sleep(1.0)

            chunk_sparse_cache: Dict[int, SparseVectorData] = {}
            points_to_upsert: List[VectorPoint] = []
            synced_ids: List[int] = []

            for row, emb_res in zip(rows, embedded_results):
                q_id = row.q_id
                q_text = row.q_text
                chunk_id = row.chunk_id
                chunk_content = row.chunk_content
                page_id = row.page_id
                page_url = row.page_url

                doc_type = classify_document_type(page_url, chunk_content)

                if chunk_id not in chunk_sparse_cache:
                    chunk_sparse_cache[chunk_id] = compute_simple_sparse_vector(chunk_content)
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
                synced_ids.append(q_id)

            if points_to_upsert:
                await vector_db.upsert_points(
                    collection_name=target_collection, points=points_to_upsert
                )
                await session.execute(
                    update(GeneratedQuestion)
                    .where(GeneratedQuestion.id.in_(synced_ids))
                    .values(is_synced_qdrant=True)
                )
                await session.commit()
                total_synced += len(points_to_upsert)

    return total_synced


async def run_full_pipeline(website_id: int) -> dict:
    async with async_session() as session:
        website = await session.get(Website, website_id)
        if not website:
            raise ValueError(f"Website with id {website_id} not found")

        website.status = WebsiteScrapeStatus.IN_PROGRESS
        website.error_message = None

        await session.execute(
            update(ScrapedPage)
            .where(
                ScrapedPage.web_id == website_id,
                ScrapedPage.status.in_([
                    PageProcessStatus.FAILED, 
                    PageProcessStatus.IN_PROGRESS
                ]),
            )
            .values(
                status=PageProcessStatus.PENDING,
                retries=0,
            )
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

    async def _qdrant_task():
        return await qdrant_sync_worker(org_id=org_id, web_id=website_id, is_qgen_done=is_qgen_done)

    try:
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
            _qdrant_task(),
        )

        async with async_session() as session:
            website = await session.get(Website, website_id)
            website.status = WebsiteScrapeStatus.COMPLETED
            await session.commit()

        return {
            "status": "COMPLETED",
            "discovered_urls": discovered_urls,
            "scraped_pages": scraped_pages,
            "created_chunks": created_chunks,
            "generated_questions": generated_questions,
            "synced_qdrant_points": synced_qdrant_points,
        }

    except Exception as e:
        async with async_session() as session:
            website = await session.get(Website, website_id)
            if website:
                website.status = WebsiteScrapeStatus.FAILED
                website.error_message = str(e)
                await session.commit()
        raise e