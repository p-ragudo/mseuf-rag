import hashlib
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload

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


def estimate_token_count(text: str) -> int:
    return max(1, len(text.split()))


def compute_simple_sparse_vector(text: str) -> SparseVectorData:
    words = [w.lower() for w in text.split() if w.isalnum()]
    if not words:
        return SparseVectorData(indices=[], values=[])

    counts = Counter(words)
    indices = []
    values = []

    for word, freq in counts.items():
        idx = int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16)
        indices.append(idx)
        values.append(float(freq))

    sorted_pairs = sorted(zip(indices, values), key=lambda x: x[0])
    return SparseVectorData(
        indices=[p[0] for p in sorted_pairs],
        values=[p[1] for p in sorted_pairs],
    )


async def scrape_pending_pages(web_id: int, max_retries: int = 3) -> int:
    scraped_count = 0
    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    async with async_session() as session:
        stmt = select(ScrapedPage).where(
            ScrapedPage.web_id == web_id,
            ScrapedPage.status == PageProcessStatus.PENDING,
            ScrapedPage.retries < max_retries,
        )
        res = await session.execute(stmt)
        pending_pages = res.scalars().all()

        if not pending_pages:
            return 0

        async with AsyncWebCrawler() as crawler:
            for page in pending_pages:
                page.status = PageProcessStatus.IN_PROGRESS
                await session.commit()

                try:
                    crawl_result = await crawler.arun(url=page.url, config=config)
                    if crawl_result.success and crawl_result.markdown:
                        page.markdown_content = crawl_result.markdown
                        page.status = PageProcessStatus.COMPLETED
                        scraped_count += 1
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

    return scraped_count


async def chunk_completed_pages(
    web_id: int,
    chunk_size: int = 800,
    chunk_overlap: int = 150,
) -> int:
    """Uses clean_markdown and RecursiveCharacterTextSplitter to produce chunks."""
    chunks_created = 0
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    async with async_session() as session:
        stmt = select(ScrapedPage).where(
            ScrapedPage.web_id == web_id,
            ScrapedPage.status == PageProcessStatus.COMPLETED,
            ScrapedPage.chunked_at.is_(None),
            ScrapedPage.markdown_content.is_not(None),
        )
        res = await session.execute(stmt)
        pages = res.scalars().all()

        for page in pages:
            raw_text = page.markdown_content or ""
            cleaned = clean_markdown(raw_text)

            if cleaned.startswith("---"):
                parts = cleaned.split("---", 2)
                if len(parts) >= 3:
                    cleaned = parts[2].strip()

            split_texts = text_splitter.split_text(cleaned)
            valid_chunks: List[Chunk] = []

            for text in split_texts:
                stripped_chunk = text.strip()
                if len(stripped_chunk) > 40:
                    valid_chunks.append(
                        Chunk(
                            page_id=page.id,
                            content=stripped_chunk,
                            token_count=estimate_token_count(stripped_chunk),
                            has_qgen=False,
                        )
                    )

            await session.execute(delete(Chunk).where(Chunk.page_id == page.id))

            if valid_chunks:
                session.add_all(valid_chunks)
                chunks_created += len(valid_chunks)

            page.chunked_at = datetime.now(timezone.utc)
            await session.commit()

    return chunks_created


async def generate_questions_for_chunks(web_id: int) -> int:
    questions_created = 0
    generator = get_question_generator()

    async with async_session() as session:
        stmt = (
            select(Chunk)
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(
                ScrapedPage.web_id == web_id,
                Chunk.has_qgen.is_(False),
            )
            .options(selectinload(Chunk.page))
        )
        res = await session.execute(stmt)
        pending_chunks = res.scalars().all()

        for chunk in pending_chunks:
            page = chunk.page
            tenant_str = str(page.org_id)
            doc_id = generate_doc_id(tenant_id=tenant_str, source_url=page.url)

            raw_chunk_payload = RawChunk(
                id=str(chunk.id),
                doc_id=doc_id,
                source_url=page.url,
                title=page.url.split("/")[-1] or "Homepage",
                content=chunk.content,
                tags=[tenant_str],
            )

            try:
                generated = await generator.generate_questions(raw_chunk_payload)

                for item in generated:
                    question_text = (
                        item.content if hasattr(item, "content") else str(item)
                    )
                    q_record = GeneratedQuestion(
                        chunk_id=chunk.id,
                        question=question_text,
                        is_synced_qdrant=False,
                    )
                    session.add(q_record)
                    questions_created += 1

                chunk.has_qgen = True
                await session.commit()

            except Exception as e:
                await session.rollback()
                print(f"[QGen Error] Failed chunk_id={chunk.id}: {e}")

    return questions_created


async def sync_questions_to_qdrant(org_id: int, web_id: int) -> int:
    points_synced = 0
    vector_db = get_vector_db()
    embedder = get_embedder()
    target_collection = settings.dense_collection_name

    await vector_db.create_collection_if_not_exists(
        collection_name=target_collection,
        dense_vector_size=embedder.dimension,
        distance="Cosine",
    )

    async with async_session() as session:
        stmt = (
            select(GeneratedQuestion)
            .join(Chunk, GeneratedQuestion.chunk_id == Chunk.id)
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(
                ScrapedPage.web_id == web_id,
                GeneratedQuestion.is_synced_qdrant.is_(False),
            )
            .options(selectinload(GeneratedQuestion.chunk).selectinload(Chunk.page))
        )
        res = await session.execute(stmt)
        unsynced_questions = res.scalars().all()

        if not unsynced_questions:
            return 0

        question_texts = [q.question for q in unsynced_questions]
        embedded_results = embedder.embed(question_texts)

        chunk_sparse_cache: Dict[int, SparseVectorData] = {}
        points_to_upsert: List[VectorPoint] = []
        synced_ids: List[int] = []

        tenant_key = str(org_id)

        for q_record, emb_res in zip(unsynced_questions, embedded_results):
            chunk = q_record.chunk
            page = chunk.page

            if chunk.id not in chunk_sparse_cache:
                chunk_sparse_cache[chunk.id] = compute_simple_sparse_vector(chunk.content)
            sparse_data = chunk_sparse_cache[chunk.id]

            chunk_uuid = generate_chunk_id(
                tenant_id=tenant_key,
                source_url=page.url,
                chunk_index=chunk.id,
                content=chunk.content,
            )
            point_uuid = generate_question_id(
                chunk_id=chunk_uuid,
                question=q_record.question,
            )

            point = VectorPoint(
                id=point_uuid,
                vector={
                    "question_dense": emb_res.values,
                    "chunk_sparse": sparse_data,
                },
                payload={
                    "group_id": tenant_key,
                    "tenant_id": tenant_key,
                    "parent_chunk_id": chunk_uuid,
                    "question_text": q_record.question,
                    "chunk_text": chunk.content,
                    "source_url": page.url,
                    "page_id": page.id,
                    "chunk_id": chunk.id,
                },
            )
            points_to_upsert.append(point)
            synced_ids.append(q_record.id)

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
            points_synced = len(points_to_upsert)

    return points_synced


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

    try:
        discovered_urls = await run_discovery(
            org_id=org_id, web_id=website_id, base_url=base_url
        )
        scraped_pages = await scrape_pending_pages(web_id=website_id)
        created_chunks = await chunk_completed_pages(web_id=website_id)
        generated_questions = await generate_questions_for_chunks(web_id=website_id)
        synced_qdrant_points = await sync_questions_to_qdrant(
            org_id=org_id, web_id=website_id
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