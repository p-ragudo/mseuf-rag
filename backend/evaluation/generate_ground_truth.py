import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy import select

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.core.database import async_session
from app.models.chunk import Chunk
from app.models.generated_question import GeneratedQuestion
from app.models.org import Org
from app.models.scraped_page import PageProcessStatus, ScrapedPage
from app.services.ingest_pipeline.orchestrator import (
    classify_academic_level,
    classify_document_type,
    extract_sub_entity_from_url,
    get_active_sync_column,
)
from app.utils.temporal import extract_doc_period
from app.utils.uuid_generator import generate_chunk_id
from evaluation.filter_heuristics import is_substantive_evaluation_chunk

BATCH_CHUNK_SIZE = 5


class SyntheticQAPair(BaseModel):
    query: str = Field(
        description="A realistic, standalone user question. If the chunk belongs to a specific campus, branch, or academic level, include that context naturally in the question."
    )
    ground_truth_answer: str = Field(
        description="A comprehensive, strictly grounded reference answer derived solely from the chunk text."
    )


class ChunkEvaluationItem(BaseModel):
    chunk_id: int = Field(
        description="The integer CHUNK ID corresponding to the evaluated block."
    )
    is_valuable: bool = Field(
        description="False if the chunk is fluff, promotional filler, or lacks concrete facts."
    )
    qa_pairs: List[SyntheticQAPair] = Field(
        default_factory=list,
        description="1 to 2 question-answer pairs if is_valuable is true, else empty list.",
    )


class BatchChunkEvaluationOutput(BaseModel):
    # Using List instead of Dict to prevent 'additionalProperties' schema error in Gemini API
    results: List[ChunkEvaluationItem] = Field(
        description="List of evaluation items, one per input chunk."
    )


def build_curator_instruction(org_name: str) -> str:
    return f"""You are a Senior QA Benchmark Curator for {org_name} (a multi-tenant RAG platform).
Your job is to analyze multiple content chunks independently and generate 1 to 2 realistic user questions and their ideal ground-truth answers for each substantive chunk.

CRITICAL MULTI-TENANT & GROUNDING RULES:
1. Strict Grounding: Every fact in `ground_truth_answer` MUST come directly from the provided chunk. Never extrapolate or use outside world knowledge.
2. Self-Contained & Entity-Specific: Users do not see the chunk when asking a question. Never write "according to this section" or "in the table above". Explicitly name the program, procedure, office, campus, or academic period (e.g., AY 2025-2026) if stated in the metadata or text.
3. Campus & Level Disambiguation: If the chunk metadata specifies a campus (other than 'main') or a specific academic level (e.g., 'shs', 'graduate'), make sure the question and answer reflect that scope so cross-campus confusion is avoided.
4. Fluff Rejection: If the chunk is purely promotional ("we nurture future leaders"), vague announcement headers without details, or boilerplate, set `is_valuable = false` and `qa_pairs = []`.
5. Return Format: Populate the 'results' list with an item for every chunk ID provided.
"""


def get_tenant_data_dir(org_id: int) -> Path:
    tenant_dir = CURRENT_DIR / "data" / f"org_{org_id}"
    tenant_dir.mkdir(parents=True, exist_ok=True)
    return tenant_dir


async def discover_indexed_tenants() -> List[Org]:
    sync_col = get_active_sync_column()
    async with async_session() as session:
        stmt = (
            select(Org)
            .join(ScrapedPage, ScrapedPage.org_id == Org.id)
            .join(Chunk, Chunk.page_id == ScrapedPage.id)
            .join(GeneratedQuestion, GeneratedQuestion.chunk_id == Chunk.id)
            .where(
                ScrapedPage.status == PageProcessStatus.COMPLETED,
                sync_col.is_(True),
            )
            .group_by(Org.id)
            .order_by(Org.id)
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())


async def fetch_tenant_chunks(org_id: int, sample_limit: int = 40) -> List[Dict[str, Any]]:
    sync_col = get_active_sync_column()

    async with async_session() as session:
        stmt = (
            select(
                Chunk.id.label("chunk_id"),
                Chunk.content.label("content"),
                Chunk.token_count.label("token_count"),
                Chunk.chunk_index.label("chunk_index"),
                Chunk.section_id.label("section_id"),
                Chunk.heading_path.label("heading_path"),
                Chunk.part_index.label("part_index"),
                Chunk.part_total.label("part_total"),
                ScrapedPage.id.label("page_id"),
                ScrapedPage.url.label("source_url"),
                ScrapedPage.doc_period.label("page_doc_period"),
            )
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(
                ScrapedPage.org_id == org_id,
                ScrapedPage.status == PageProcessStatus.COMPLETED,
                Chunk.id.in_(
                    select(GeneratedQuestion.chunk_id).where(sync_col.is_(True))
                ),
            )
            .order_by(ScrapedPage.id, Chunk.chunk_index)
        )
        rows = (await session.execute(stmt)).all()

    substantive: List[Dict[str, Any]] = []
    seen_hashes = set()

    for r in rows:
        if not is_substantive_evaluation_chunk(
            text=r.content,
            heading_path=r.heading_path or "",
            source_url=r.source_url,
        ):
            continue

        norm_prefix = " ".join(r.content.lower().split()[:30])
        if norm_prefix in seen_hashes:
            continue
        seen_hashes.add(norm_prefix)

        campus = extract_sub_entity_from_url(r.source_url)
        academic_level = classify_academic_level(r.source_url, r.content)
        doc_type = classify_document_type(r.source_url, r.content)
        doc_period = (
            extract_doc_period(
                r.content, url=r.source_url, heading=r.heading_path or ""
            )
            or r.page_doc_period
        )
        parent_chunk_uuid = generate_chunk_id(
            tenant_id=str(org_id),
            source_url=r.source_url,
            chunk_index=r.chunk_id,
            content=r.content,
        )

        substantive.append(
            {
                "chunk_id": r.chunk_id,
                "parent_chunk_uuid": parent_chunk_uuid,
                "page_id": r.page_id,
                "source_url": r.source_url,
                "section_id": r.section_id or "",
                "heading_path": r.heading_path or "",
                "chunk_index": r.chunk_index,
                "part_index": r.part_index,
                "part_total": r.part_total,
                "campus": campus,
                "academic_level": academic_level,
                "doc_type": doc_type,
                "doc_period": f"{doc_period}-{doc_period + 1}" if isinstance(doc_period, int) else None,
                "content": r.content,
            }
        )

    by_page: Dict[int, List[Dict[str, Any]]] = {}
    for item in substantive:
        by_page.setdefault(item["page_id"], []).append(item)

    sampled: List[Dict[str, Any]] = []
    page_queues = list(by_page.values())
    while page_queues and len(sampled) < sample_limit:
        next_queues = []
        for q in page_queues:
            if q and len(sampled) < sample_limit:
                sampled.append(q.pop(0))
            if q:
                next_queues.append(q)
        page_queues = next_queues

    return sampled


async def generate_for_tenant(
    org: Org,
    sample_limit: int = 40,
    filename: str = "ground_truth.jsonl",
) -> Path:
    tenant_dir = get_tenant_data_dir(org.id)
    output_path = tenant_dir / filename
    meta_path = tenant_dir / "metadata.json"

    print(f"\n" + "=" * 65)
    print(f"Generating Ground Truth for Tenant: {org.name} (org_id={org.id})")
    print("=" * 65)

    chunks = await fetch_tenant_chunks(org_id=org.id, sample_limit=sample_limit)
    if not chunks:
        print(f"[Skip] No substantive synced chunks found for org_id={org.id}.")
        return output_path

    print(f"Selected {len(chunks)} substantive chunks across tenant pages. (Batch size: {BATCH_CHUNK_SIZE})")

    api_key = settings.llm_qgen_api_key or settings.llm_qa_api_key
    client = genai.Client(api_key=api_key)
    system_instruction = build_curator_instruction(org.name)
    curator_model = "gemini-3.8-flash"

    records_written = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for i in range(0, len(chunks), BATCH_CHUNK_SIZE):
            batch_slice = chunks[i : i + BATCH_CHUNK_SIZE]
            batch_map = {c["chunk_id"]: c for c in batch_slice}

            formatted_blocks = []
            for c in batch_slice:
                formatted_blocks.append(
                    f"--- START CHUNK ID: {c['chunk_id']} ---\n"
                    f"Source URL: {c['source_url']}\n"
                    f"Campus: {c['campus']}\n"
                    f"Academic Level: {c['academic_level']}\n"
                    f"Academic Period: {c['doc_period'] or 'Unspecified'}\n"
                    f"Heading Path: {c['heading_path'] or 'Root'}\n"
                    f"Content:\n{c['content']}\n"
                    f"--- END CHUNK ID: {c['chunk_id']} ---"
                )

            prompt = (
                f"Analyze each of the following {len(batch_slice)} chunks independently for tenant '{org.name}'.\n\n"
                + "\n\n".join(formatted_blocks)
            )

            response = None
            for attempt in range(3):
                try:
                    response = await client.aio.models.generate_content(
                        model=curator_model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            response_mime_type="application/json",
                            response_schema=BatchChunkEvaluationOutput,
                            temperature=0.1,
                            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                                disable=True
                            ),
                        ),
                    )
                    break
                except Exception as e:
                    if attempt < 2:
                        await asyncio.sleep(2.5 * (2 ** attempt))
                    else:
                        print(f"  [Error] Batch {i}..{i+len(batch_slice)} failed after retries: {e}")

            if not response or not response.text:
                continue

            try:
                parsed = json.loads(response.text)
                results_list = parsed.get("results", [])
            except Exception as e:
                print(f"  [Parse Error] Batch {i}..{i+len(batch_slice)}: {e}")
                continue

            for item in results_list:
                cid = item.get("chunk_id")
                if cid not in batch_map:
                    continue
                chunk_data = batch_map[cid]

                if not item.get("is_valuable"):
                    print(f"  Chunk {cid} marked non-valuable (fluff/boilerplate).")
                    continue

                qa_pairs = item.get("qa_pairs", [])
                for q_idx, qa in enumerate(qa_pairs, start=1):
                    record = {
                        "test_id": f"org{org.id}_c{chunk_data['chunk_id']}_q{q_idx}",
                        "org_id": org.id,
                        "org_name": org.name,
                        "content_version": org.content_version,
                        "user_query": qa["query"].strip(),
                        "ground_truth_answer": qa["ground_truth_answer"].strip(),
                        "ground_truth_chunk_ids": [chunk_data["chunk_id"]],
                        "ground_truth_parent_uuids": [chunk_data["parent_chunk_uuid"]],
                        "ground_truth_section_id": chunk_data["section_id"],
                        "ground_truth_contexts": [chunk_data["content"]],
                        "source_url": chunk_data["source_url"],
                        "heading_path": chunk_data["heading_path"],
                        "campus": chunk_data["campus"],
                        "academic_level": chunk_data["academic_level"],
                        "doc_period": chunk_data["doc_period"],
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    records_written += 1

                print(f"  Batch item Chunk {cid} ({chunk_data['campus']}): +{len(qa_pairs)} QA pairs")

            await asyncio.sleep(0.5)

    metadata = {
        "org_id": org.id,
        "org_name": org.name,
        "content_version_at_generation": org.content_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chunks_evaluated": len(chunks),
        "total_qa_pairs": records_written,
        "dataset_file": filename,
        "active_collection": settings.resolved_collection_name,
        "curator_model": curator_model,
        "embedding_model": settings.embedding_model,
    }
    with open(meta_path, "w", encoding="utf-8") as mf:
        json.dump(metadata, mf, indent=2)

    print(f"\nSaved {records_written} ground-truth pairs to: {output_path.resolve()}")
    return output_path


async def main():
    parser = argparse.ArgumentParser(
        description="Multi-tenant synthetic ground-truth generator."
    )
    parser.add_argument(
        "--org-id",
        type=int,
        nargs="+",
        help="One or more specific organization IDs (e.g. --org-id 1 2).",
    )
    parser.add_argument(
        "--all-orgs",
        action="store_true",
        help="Automatically generate ground-truth datasets for all indexed tenants.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="Max substantive chunks to sample per tenant (default: 40).",
    )
    parser.add_argument(
        "--filename",
        type=str,
        default="ground_truth.jsonl",
        help="Filename inside evaluation/data/org_<id>/ (default: ground_truth.jsonl).",
    )
    args = parser.parse_args()

    if not args.org_id and not args.all_orgs:
        parser.error("Provide either --org-id <id...> or --all-orgs.")

    target_orgs: List[Org] = []
    if args.all_orgs:
        target_orgs = await discover_indexed_tenants()
    else:
        async with async_session() as session:
            for oid in args.org_id:
                org = await session.get(Org, oid)
                if org:
                    target_orgs.append(org)
                else:
                    print(f"[Warning] Org ID {oid} not found in PostgreSQL.")

    if not target_orgs:
        print("No valid organizations found to process.")
        return

    for org in target_orgs:
        await generate_for_tenant(
            org=org,
            sample_limit=args.limit,
            filename=args.filename,
        )


if __name__ == "__main__":
    asyncio.run(main())