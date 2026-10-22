import asyncio
import sys
from pathlib import Path

# Automatically inject backend/ into sys.path so 'app' imports work correctly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from app.core.database import async_session
from app.models.chunk import Chunk
from app.models.scraped_page import ScrapedPage
from app.services.ingest_pipeline.orchestrator import extract_sub_entity_from_url
from evaluation.common import content_sha, tenant_dir, write_jsonl

TARGET_FAQ_URL = "https://mseuf.edu.ph/admission/pages/frequently-asked-questions-admissions-procedure"

async def generate_faq_dataset(org_id: int = 1):
    async with async_session() as session:
        # Filter specifically for chunks belonging to the MSEUF admissions FAQ URL
        stmt = (
            select(
                Chunk.id.label("chunk_id"),
                Chunk.content.label("content"),
                Chunk.heading_path.label("heading_path"),
                ScrapedPage.url.label("source_url")
            )
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(
                ScrapedPage.org_id == org_id,
                ScrapedPage.url == TARGET_FAQ_URL
            )
        )
        rows = (await session.execute(stmt)).all()

    if not rows:
        print(f"[Warning] No chunks found for URL: {TARGET_FAQ_URL}")
        print("Tip: Make sure the FAQ page has been successfully scraped and ingested into Postgres first.")
        return

    records = []
    for idx, r in enumerate(rows, start=1):
        content = r.content.strip()
        
        # Use the chunk's heading path or default to a clean label if empty
        query = r.heading_path.strip() if r.heading_path else f"MSEUF Admissions FAQ Item {idx}"
        
        records.append({
            "test_id": f"org{org_id}_mseuf_faq_{idx}",
            "set_name": "faqs",
            "answerable": True,
            "org_id": org_id,
            "org_name": "mseuf",
            "content_version": 1,
            "user_query": query,
            "ground_truth_answer": content,
            "primary_chunk_id": int(r.chunk_id),
            "ground_truth_chunk_ids": [int(r.chunk_id)],
            "ground_truth_contexts": [content],
            "ground_truth_content_sha": content_sha(content),
            "source_url": r.source_url,
            "heading_path": r.heading_path or "",
            "campus": extract_sub_entity_from_url(r.source_url),
        })

    out_path = tenant_dir(org_id, create=True) / "ground_truth_faqs.jsonl"
    n = write_jsonl(out_path, records)
    print(f"Successfully generated {n} MSEUF FAQ evaluation records at {out_path.resolve()}")

if __name__ == "__main__":
    asyncio.run(generate_faq_dataset(org_id=1))