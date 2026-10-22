"""Builds the test sets. READ-ONLY on Postgres (SELECTs only); writes local files under evaluation/data/org_<id>/.

Sets (all stored in one JSONL, distinguished by `set_name`):
  synthetic_standard   - 1-2 formal, self-contained questions per sampled chunk (like the original generator)
  synthetic_colloquial - 1 short, informal question per SAME chunk, different prompt (and optionally different model).
                         Comparing the two on the same gold chunks measures how much of your score is 'easy phrasing'.
  negative             - questions the knowledge base should NOT be able to answer (off-topic + plausible-but-absent)
                         -> measures hallucination / abstention and lets us calibrate the reranker threshold.

Usage:  uv run python -m evaluation.generate_ground_truth --org-id 1 --limit 40
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
from evaluation.common import content_sha, tenant_dir, write_jsonl
from evaluation.filter_heuristics import is_substantive_evaluation_chunk
from evaluation.safety import install_postgres_write_guard

BATCH_CHUNK_SIZE = 5
DEFAULT_CURATOR_MODEL = "gemini-3.8-flash"

OFF_TOPIC_QUESTIONS = [
    "What is the capital of France?",
    "Write me a short poem about the sea.",
    "Who won the NBA championship last year?",
    "How do I fix a flat bicycle tire?",
    "What is the best way to invest in the stock market?",
    "Can you recommend a good recipe for chicken adobo?",
]


class SyntheticQAPair(BaseModel):
    query: str = Field(description="A realistic, standalone user question.")
    ground_truth_answer: str = Field(description="A strictly grounded reference answer derived solely from the chunk text.")


class ChunkEvaluationItem(BaseModel):
    chunk_id: int = Field(description="The integer CHUNK ID corresponding to the evaluated block.")
    is_valuable: bool = Field(description="False if the chunk is fluff, promotional filler, or lacks concrete facts.")
    qa_pairs: List[SyntheticQAPair] = Field(default_factory=list)


class BatchChunkEvaluationOutput(BaseModel):
    results: List[ChunkEvaluationItem]


class NegativeQuestionSet(BaseModel):
    questions: List[str]


def build_curator_instruction(org_name: str, style: str) -> str:
    common = f"""You are a Senior QA Benchmark Curator for {org_name} (a multi-tenant RAG platform).
Analyze each content chunk independently.

GROUNDING RULES
1. Every fact in `ground_truth_answer` MUST come directly from the chunk. Never use outside knowledge.
2. Users do not see the chunk. Never write "according to this section" or "in the table above".
3. Campus & level: if the metadata names a campus (other than 'main') or level (e.g. 'shs', 'graduate'), keep that scope
   in the question and answer so cross-campus confusion is avoided.
4. Fluff rejection: promotional text, vague announcement headers or boilerplate -> is_valuable=false, qa_pairs=[].
5. Return one item for every chunk ID provided."""
    if style == "standard":
        return common + """
STYLE: write 1 to 2 clear, formal, self-contained questions per valuable chunk. Name the program, office, campus or
academic period explicitly when stated."""
    return common + """
STYLE: write exactly ONE question per valuable chunk, the way a real prospective student, parent or employee would type
into a chat box: short, informal, sometimes incomplete, occasionally Taglish when natural. Do NOT copy distinctive phrases
or headings from the chunk; paraphrase with everyday words. Keep the key entity (program / office / campus) because
without it the question would be ambiguous, but drop formal wording and academic-year boilerplate unless essential.
The question must still be fully answerable from the chunk."""


# ------------------------------------------------------------------------------------------
# DB reads
# ------------------------------------------------------------------------------------------

async def discover_indexed_tenants() -> List[Org]:
    sync_col = get_active_sync_column()
    async with async_session() as session:
        stmt = (
            select(Org)
            .join(ScrapedPage, ScrapedPage.org_id == Org.id)
            .join(Chunk, Chunk.page_id == ScrapedPage.id)
            .join(GeneratedQuestion, GeneratedQuestion.chunk_id == Chunk.id)
            .where(ScrapedPage.status == PageProcessStatus.COMPLETED, sync_col.is_(True))
            .group_by(Org.id)
            .order_by(Org.id)
        )
        return list((await session.execute(stmt)).scalars().all())


async def fetch_equivalence_groups(org_id: int) -> Dict[Tuple[str, str], List[int]]:
    """(normalised-content hash, campus) -> chunk ids. Exact same-campus duplicates are all valid gold answers."""
    async with async_session() as session:
        rows = (
            await session.execute(
                select(Chunk.id, Chunk.content, ScrapedPage.url)
                .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
                .where(ScrapedPage.org_id == org_id, ScrapedPage.status == PageProcessStatus.COMPLETED)
            )
        ).all()
    groups: Dict[Tuple[str, str], List[int]] = {}
    for cid, content, url in rows:
        key = (content_sha(content), extract_sub_entity_from_url(url))
        groups.setdefault(key, []).append(int(cid))
    return groups


async def fetch_tenant_chunks(org_id: int, sample_limit: int) -> List[Dict[str, Any]]:
    sync_col = get_active_sync_column()
    async with async_session() as session:
        stmt = (
            select(
                Chunk.id.label("chunk_id"), Chunk.content.label("content"), Chunk.chunk_index.label("chunk_index"),
                Chunk.section_id.label("section_id"), Chunk.heading_path.label("heading_path"),
                ScrapedPage.id.label("page_id"), ScrapedPage.url.label("source_url"),
                ScrapedPage.doc_period.label("page_doc_period"),
            )
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(
                ScrapedPage.org_id == org_id,
                ScrapedPage.status == PageProcessStatus.COMPLETED,
                Chunk.id.in_(select(GeneratedQuestion.chunk_id).where(sync_col.is_(True))),
            )
            .order_by(ScrapedPage.id, Chunk.chunk_index)
        )
        rows = (await session.execute(stmt)).all()

    substantive: List[Dict[str, Any]] = []
    seen = set()
    for r in rows:
        if not is_substantive_evaluation_chunk(r.content, r.heading_path or "", r.source_url):
            continue
        prefix = " ".join(r.content.lower().split()[:30])
        if prefix in seen:
            continue
        seen.add(prefix)
        doc_period = extract_doc_period(r.content, url=r.source_url, heading=r.heading_path or "") or r.page_doc_period
        substantive.append({
            "chunk_id": int(r.chunk_id),
            "page_id": r.page_id,
            "source_url": r.source_url,
            "section_id": r.section_id or "",
            "heading_path": r.heading_path or "",
            "chunk_index": r.chunk_index,
            "campus": extract_sub_entity_from_url(r.source_url),
            "academic_level": classify_academic_level(r.source_url, r.content),
            "doc_type": classify_document_type(r.source_url, r.content),
            "doc_period": f"{doc_period}-{doc_period + 1}" if isinstance(doc_period, int) else None,
            "content": r.content,
        })

    # round-robin over pages so no single page dominates the sample
    by_page: Dict[int, List[Dict[str, Any]]] = {}
    for item in substantive:
        by_page.setdefault(item["page_id"], []).append(item)
    sampled: List[Dict[str, Any]] = []
    queues = list(by_page.values())
    while queues and len(sampled) < sample_limit:
        nxt = []
        for q in queues:
            if q and len(sampled) < sample_limit:
                sampled.append(q.pop(0))
            if q:
                nxt.append(q)
        queues = nxt
    return sampled


# ------------------------------------------------------------------------------------------
# LLM calls
# ------------------------------------------------------------------------------------------

async def _call_json(client, model: str, system_instruction: str, prompt: str, schema, temperature: float):
    for attempt in range(3):
        try:
            resp = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=temperature,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            if resp.text:
                return json.loads(resp.text)
        except Exception as e:  # noqa: BLE001
            print(f"  [LLM retry {attempt + 1}/3] {e}")
        await asyncio.sleep(2.5 * (2 ** attempt))
    return None


async def curate_chunks(client, model: str, org: Org, chunks: List[Dict[str, Any]], style: str,
                        groups: Dict[Tuple[str, str], List[int]]) -> List[Dict[str, Any]]:
    set_name = "synthetic_standard" if style == "standard" else "synthetic_colloquial"
    tag = "s" if style == "standard" else "c"
    system_instruction = build_curator_instruction(org.name, style)
    records: List[Dict[str, Any]] = []

    for i in range(0, len(chunks), BATCH_CHUNK_SIZE):
        batch = chunks[i : i + BATCH_CHUNK_SIZE]
        by_id = {c["chunk_id"]: c for c in batch}
        blocks = [
            f"--- START CHUNK ID: {c['chunk_id']} ---\nSource URL: {c['source_url']}\nCampus: {c['campus']}\n"
            f"Academic Level: {c['academic_level']}\nAcademic Period: {c['doc_period'] or 'Unspecified'}\n"
            f"Heading Path: {c['heading_path'] or 'Root'}\nContent:\n{c['content']}\n--- END CHUNK ID: {c['chunk_id']} ---"
            for c in batch
        ]
        prompt = f"Analyze each of the following {len(batch)} chunks independently for tenant '{org.name}'.\n\n" + "\n\n".join(blocks)
        parsed = await _call_json(client, model, system_instruction, prompt, BatchChunkEvaluationOutput,
                                  temperature=0.1 if style == "standard" else 0.4)
        if not parsed:
            print(f"  [Skip] batch {i}..{i + len(batch)} failed ({style}).")
            continue
        for item in parsed.get("results", []):
            cid = item.get("chunk_id")
            if cid not in by_id or not item.get("is_valuable"):
                continue
            c = by_id[cid]
            gold_ids = sorted(set(groups.get((content_sha(c["content"]), c["campus"]), [])) | {cid})
            pairs = item.get("qa_pairs", [])[: (2 if style == "standard" else 1)]
            for q_idx, qa in enumerate(pairs, start=1):
                records.append({
                    "test_id": f"org{org.id}_c{cid}_{tag}{q_idx}",
                    "set_name": set_name,
                    "answerable": True,
                    "org_id": org.id,
                    "org_name": org.name,
                    "content_version": org.content_version,
                    "user_query": qa["query"].strip(),
                    "ground_truth_answer": qa["ground_truth_answer"].strip(),
                    "primary_chunk_id": cid,
                    "ground_truth_chunk_ids": gold_ids,
                    "ground_truth_contexts": [c["content"]],
                    "ground_truth_content_sha": content_sha(c["content"]),
                    "ground_truth_section_id": c["section_id"],
                    "source_url": c["source_url"],
                    "heading_path": c["heading_path"],
                    "campus": c["campus"],
                    "academic_level": c["academic_level"],
                    "doc_period": c["doc_period"],
                })
        print(f"  [{style}] chunks {i + 1}-{i + len(batch)} done, {len(records)} records so far")
        await asyncio.sleep(0.5)
    return records


async def generate_negatives(client, model: str, org: Org, chunks: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    def _rec(i: int, q: str, kind: str, review: bool) -> Dict[str, Any]:
        return {
            "test_id": f"org{org.id}_neg{i}", "set_name": "negative", "answerable": False, "negative_kind": kind,
            "needs_review": review, "org_id": org.id, "org_name": org.name, "content_version": org.content_version,
            "user_query": q, "ground_truth_answer": None, "primary_chunk_id": None, "ground_truth_chunk_ids": [],
            "ground_truth_contexts": [], "source_url": None,
        }

    for q in OFF_TOPIC_QUESTIONS:
        records.append(_rec(len(records) + 1, q, "off_topic", False))

    if n > 0:
        headings = sorted({c["heading_path"] for c in chunks if c["heading_path"]})[:80]
        prompt = (
            f"Institution: {org.name}\nTopics covered by its knowledge base (headings):\n- " + "\n- ".join(headings or ["(none)"]) +
            f"\n\nWrite {n} realistic questions a prospective student, parent or employee might ask this institution's "
            "information office that are NOT answered by any topic above (services, policies, people, prices or events the "
            "list never mentions). Each must be specific enough that an answer would require facts we do not have."
        )
        parsed = await _call_json(client, model, "You write test questions for a retrieval-augmented chatbot.", prompt,
                                  NegativeQuestionSet, temperature=0.6)
        for q in (parsed or {}).get("questions", [])[:n]:
            records.append(_rec(len(records) + 1, str(q).strip(), "plausible_absent", True))
    return records


# ------------------------------------------------------------------------------------------

async def generate_for_tenant(org: Org, args) -> Optional[Path]:
    out_dir = tenant_dir(org.id, create=True)
    output_path = out_dir / args.filename
    if output_path.exists() and not args.overwrite:
        raise SystemExit(f"{output_path} exists. Use --overwrite or choose --filename.")

    print("\n" + "=" * 65 + f"\nGenerating test sets for {org.name} (org_id={org.id})\n" + "=" * 65)
    chunks = await fetch_tenant_chunks(org.id, args.limit)
    if not chunks:
        print("[Skip] no substantive synced chunks.")
        return None
    groups = await fetch_equivalence_groups(org.id)
    print(f"Sampled {len(chunks)} chunks. Exact duplicate groups: {sum(1 for v in groups.values() if len(v) > 1)}")

    api_key = settings.llm_qgen_api_key or settings.llm_qa_api_key
    client = genai.Client(api_key=api_key)

    records: List[Dict[str, Any]] = []
    if "standard" in args.sets:
        records += await curate_chunks(client, args.curator_model, org, chunks, "standard", groups)
    if "colloquial" in args.sets:
        records += await curate_chunks(client, args.colloquial_model or args.curator_model, org, chunks, "colloquial", groups)
    if "negative" in args.sets:
        records += await generate_negatives(client, args.curator_model, org, chunks, args.negatives)

    n = write_jsonl(output_path, records)
    meta = {
        "org_id": org.id, "org_name": org.name, "content_version_at_generation": org.content_version,
        "generated_at": datetime.now(timezone.utc).isoformat(), "chunks_sampled": len(chunks), "records": n,
        "per_set": {s: sum(1 for r in records if r["set_name"] == s) for s in {r["set_name"] for r in records}},
        "dataset_file": args.filename, "active_collection": settings.resolved_collection_name,
        "curator_model": args.curator_model, "colloquial_model": args.colloquial_model or args.curator_model,
        "embedding_model": settings.embedding_model,
    }
    output_path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nWrote {n} records to {output_path.resolve()}")
    if "negative" in args.sets:
        print("Review the 'plausible_absent' negatives by eye (needs_review=true): make sure the site really cannot answer them.")
    return output_path


async def main() -> None:
    p = argparse.ArgumentParser(description="Multi-tenant synthetic ground-truth generator (read-only on the DB).")
    p.add_argument("--org-id", type=int, nargs="+")
    p.add_argument("--all-orgs", action="store_true")
    p.add_argument("--limit", type=int, default=40, help="Chunks to sample per tenant (default 40).")
    p.add_argument("--sets", nargs="+", default=["standard", "colloquial", "negative"],
                   choices=["standard", "colloquial", "negative"])
    p.add_argument("--filename", default="ground_truth_v2.jsonl")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--curator-model", default=DEFAULT_CURATOR_MODEL)
    p.add_argument("--colloquial-model", default=None, help="Use a DIFFERENT model here to reduce self-similarity.")
    p.add_argument("--negatives", type=int, default=10, help="LLM-written plausible-but-absent questions (plus 6 off-topic).")
    args = p.parse_args()
    if not args.org_id and not args.all_orgs:
        p.error("Provide --org-id or --all-orgs.")

    install_postgres_write_guard()  # this script only SELECTs; the guard proves it
    orgs: List[Org] = []
    if args.all_orgs:
        orgs = await discover_indexed_tenants()
    else:
        async with async_session() as session:
            for oid in args.org_id:
                org = await session.get(Org, oid)
                if org:
                    orgs.append(org)
                else:
                    print(f"[Warning] Org {oid} not found.")
    for org in orgs:
        await generate_for_tenant(org, args)


if __name__ == "__main__":
    asyncio.run(main())
