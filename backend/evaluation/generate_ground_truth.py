"""Builds and structures the three evaluation datasets (100 + 21 + 71 = 192 total entries).
READ-ONLY on Postgres (SELECTs only); writes local files under evaluation/data/org_<id>/.

Specifically:
  1. `ground_truth_100.jsonl`: Reduces the 259 synthetic QA pairs in `ground_truth.jsonl` to EXACTLY 100 entries,
     balanced across 3 domain clusters (`faqs_procedures`: 34, `specs_programs`: 33, `policies_announcements`: 33)
     and divided into 3 difficulty tiers:
       - Easy   (40 entries): Single-hop (1 chunk), stratified across URLs/campuses from the 259 synthetic pairs
       - Medium (35 entries): Cross-referencing 2-3 chunks from the 259-pair pool (Generated in English, Tagalog, Taglish)
       - Hard   (25 entries): Multi-hop / aggregation / calculation across 2-3 chunks (Generated in English, Tagalog, Taglish)
  2. `ground_truth_faqs_21.jsonl`: Prepares the 21 official FAQ QA pairs (`set_name="faqs"`) and resolves their
     live SQL `Chunk.id`s so they are never falsely dropped as stale. Base queries remain English.
  3. `queries_real_users_71.jsonl`: Prepares the 71 real-user queries (`set_name="real_user"`, `has_ground_truth=False`)
     for reference-free evaluation. Kept exactly as real users typed them.

Usage:
  uv run python -m evaluation.generate_ground_truth --org-id 1 --overwrite
"""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from app.models.org import Org
from app.models.scraped_page import PageProcessStatus, ScrapedPage
from evaluation.common import (
    content_sha,
    infer_domain_cluster,
    normalize_ws,
    read_jsonl,
    tenant_dir,
    write_jsonl,
)
from evaluation.safety import install_postgres_write_guard
from evaluation.traditional_metrics import gold_anchors

DEFAULT_CURATOR_MODEL = "gemini-2.5-flash"

# Exact 100-entry matrix for the Synthetic Dataset (Domain Cluster x Difficulty Tier):
#   faqs_procedures        (34) = 14 easy + 12 medium + 8 hard
#   specs_programs         (33) = 13 easy + 12 medium + 8 hard
#   policies_announcements (33) = 13 easy + 11 medium + 9 hard
#   ----------------------------------------------------------
#   Total                  (100)= 40 easy + 35 medium + 25 hard
SYNTHETIC_100_PLAN = {
    "faqs_procedures": {"easy": 14, "medium": 12, "hard": 8},
    "specs_programs": {"easy": 13, "medium": 12, "hard": 8},
    "policies_announcements": {"easy": 13, "medium": 11, "hard": 9},
}


class MultiHopQAPair(BaseModel):
    query: str = Field(description="Standalone question requiring all provided chunks to answer completely.")
    ground_truth_answer: str = Field(
        description="Complete, strictly grounded reference answer combining/calculating facts across the chunks."
    )
    difficulty: str = Field(description="'medium' for cross-referencing or 'hard' for calculation/aggregation/multi-hop.")
    reasoning_type: str = Field(
        description="e.g. 'cross_reference_comparison', 'numeric_aggregation', 'date_duration_calculation', 'multi_step_synthesis'"
    )


def _build_multihop_instruction(org_name: str, difficulty: str, language: str) -> str:
    if difficulty == "medium":
        return f"""You are a Senior RAG Benchmark Architect for {org_name}.
You are given 2 to 3 related document chunks from {org_name}'s knowledge base.
Write ONE realistic user question (written in {language}) and its strictly grounded reference answer (written in English) that REQUIRES cross-referencing facts from AT LEAST TWO of the provided chunks.
Examples of Medium (Cross-Referencing) tasks:
- Comparing document requirements or procedures between two different applicant types, grade levels, or campuses.
- Connecting an academic program or office mentioned in one chunk with its faculty, requirements, or schedule in another chunk.
STRICT RULES:
1. Do NOT invent facts outside the provided chunks.
2. Never say "according to chunk 1" or "in the text".
3. Set difficulty="medium"."""
    return f"""You are a Senior RAG Benchmark Architect for {org_name}.
You are given 2 to 3 related document chunks from {org_name}'s knowledge base.
Write ONE realistic, challenging user question (written in {language}) and its strictly grounded reference answer (written in English) that REQUIRES multi-hop reasoning, counting, numeric aggregation, or date/duration calculation across the chunks.
Examples of Hard (Multi-Hop / Aggregation / Calculation) tasks:
- Calculating the total number of copies/photos/documents needed if two siblings of different levels apply together.
- Counting total scholarship qualifiers, awards, or days suspended across multiple announcements/sections.
- Synthesizing multi-step conditional policies across chunks (e.g., if an applicant fails a specific test or applies across two categories, what combined steps, offices, and requirements apply).
STRICT RULES:
1. Every number, date, and condition in `ground_truth_answer` must be verifiable from the chunks. Show the exact breakdown in `ground_truth_answer`.
2. Never say "according to chunk 1".
3. Set difficulty="hard"."""


async def resolve_chunk_ids_for_texts(
    org_id: int, contexts: List[str], source_url: Optional[str] = None
) -> List[int]:
    """Maps ground_truth_contexts (e.g. from ground_truth_faqs.jsonl) to live SQL Chunk.id values."""
    if not contexts:
        return []
    async with async_session() as session:
        stmt = (
            select(Chunk.id, Chunk.content, ScrapedPage.url)
            .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
            .where(ScrapedPage.org_id == org_id, ScrapedPage.status == PageProcessStatus.COMPLETED)
        )
        rows = (await session.execute(stmt)).all()

    norm_rows = [(int(cid), normalize_ws(content), url) for cid, content, url in rows]
    matched_ids: List[int] = []
    for ctx in contexts:
        norm_ctx = normalize_ws(ctx)
        if not norm_ctx:
            continue
        anchors = gold_anchors(ctx, n=3, length=55)
        cands = [
            cid
            for cid, nc, u in norm_rows
            if (not source_url or u == source_url)
            and (norm_ctx[:70] in nc or (anchors and all(a in nc for a in anchors)))
        ]
        if not cands:
            cands = [
                cid
                for cid, nc, _ in norm_rows
                if norm_ctx[:60] in nc
                or (anchors and sum(1 for a in anchors if a in nc) >= max(1, len(anchors) - 1))
            ]
        for cid in cands:
            if cid not in matched_ids:
                matched_ids.append(cid)
    return matched_ids


def _extract_unique_chunks_from_259(syn_259: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extracts unique source chunks from the 259 synthetic pairs, classified into the 3 domain clusters."""
    by_chunk_id: Dict[int, Dict[str, Any]] = {}
    for r in syn_259:
        cids = [int(x) for x in (r.get("ground_truth_chunk_ids") or []) if x is not None]
        ctxs = r.get("ground_truth_contexts") or []
        if not cids or not ctxs:
            continue
        cid = cids[0]
        if cid in by_chunk_id:
            continue
        text = ctxs[0]
        url = r.get("source_url") or ""
        heading = r.get("heading_path") or ""
        cluster = infer_domain_cluster(url, heading, text)
        has_numbers = len(re.findall(r"\b\d+\b", text)) >= 3
        by_chunk_id[cid] = {
            "chunk_id": cid,
            "content": text,
            "source_url": url,
            "heading_path": heading,
            "campus": r.get("campus") or "main",
            "academic_level": r.get("academic_level") or "undergraduate",
            "doc_period": r.get("doc_period"),
            "section_id": r.get("ground_truth_section_id") or "",
            "domain_cluster": cluster,
            "has_numbers": has_numbers,
        }
    return list(by_chunk_id.values())


def _stratified_select_easy(
    syn_259: List[Dict[str, Any]], cluster: str, count_needed: int
) -> List[Dict[str, Any]]:
    """Selects `count_needed` single-hop (Easy) records from the 259 pool for `cluster`, round-robin across URLs/campuses."""
    pool = [
        r
        for r in syn_259
        if infer_domain_cluster(
            r.get("source_url") or "",
            r.get("heading_path") or "",
            (r.get("ground_truth_contexts") or [""])[0],
        )
        == cluster
    ]
    # Group by source_url so we maximize page/campus diversity
    by_url: Dict[str, List[Dict[str, Any]]] = {}
    for r in pool:
        by_url.setdefault(r.get("source_url") or "", []).append(r)

    selected: List[Dict[str, Any]] = []
    seen_chunk_ids = set()
    queues = [list(v) for v in by_url.values()]

    # Pass 1: At most 1 question per unique chunk_id across diverse URLs
    while queues and len(selected) < count_needed:
        next_queues = []
        for q in queues:
            while q and len(selected) < count_needed:
                cand = q.pop(0)
                cid = (cand.get("ground_truth_chunk_ids") or [None])[0]
                if cid not in seen_chunk_ids:
                    seen_chunk_ids.add(cid)
                    selected.append(cand)
                    break
            if q:
                next_queues.append(q)
        queues = next_queues

    # Pass 2 & 3: Top up if needed
    if len(selected) < count_needed:
        for r in pool:
            if r not in selected and len(selected) < count_needed:
                selected.append(r)
    if len(selected) < count_needed:
        for r in syn_259:
            if r not in selected and len(selected) < count_needed:
                selected.append(r)

    out: List[Dict[str, Any]] = []
    for idx, r in enumerate(selected[:count_needed], start=1):
        cids = [int(x) for x in (r.get("ground_truth_chunk_ids") or []) if x is not None]
        ctxs = r.get("ground_truth_contexts") or []
        item = dict(r)
        item["test_id"] = f"org{r.get('org_id', 1)}_syn100_{cluster[:4]}_easy_{idx}"
        item["set_name"] = "synthetic_100"
        item["domain_cluster"] = cluster
        item["difficulty"] = "easy"
        item["reasoning_type"] = "single_hop"
        item["answerable"] = True
        item["has_ground_truth"] = True
        item["base_user_query"] = r["user_query"].strip()
        item["blind_user_query"] = None
        item["primary_chunk_id"] = cids[0] if cids else None
        item["required_chunk_ids"] = cids[:1]
        item["ground_truth_chunk_ids"] = cids
        if ctxs:
            item["ground_truth_content_sha"] = content_sha(ctxs[0])
        out.append(item)
    return out


def _bundle_chunks(
    chunks: List[Dict[str, Any]],
    cluster: str,
    count_needed: int,
    group_size: int,
    prefer_numeric: bool = False,
) -> List[List[Dict[str, Any]]]:
    """Creates `count_needed` distinct multi-chunk bundles (2-3 chunks each) within `cluster`."""
    pool = [c for c in chunks if c["domain_cluster"] == cluster]
    if prefer_numeric:
        num_pool = [c for c in pool if c.get("has_numbers")]
        if len(num_pool) >= group_size * 2:
            pool = num_pool + [c for c in pool if not c.get("has_numbers")]
    if len(pool) < group_size:
        pool = list(chunks)

    bundles: List[List[Dict[str, Any]]] = []
    n = len(pool)
    for i in range(count_needed):
        bundle: List[Dict[str, Any]] = []
        seen_ids = set()
        for g in range(group_size):
            cand = pool[(i * 2 + g * max(1, (i % 3) + 1)) % n]
            if cand["chunk_id"] in seen_ids:
                for alt in pool:
                    if alt["chunk_id"] not in seen_ids:
                        cand = alt
                        break
            seen_ids.add(cand["chunk_id"])
            bundle.append(cand)
        bundles.append(bundle)
    return bundles


async def _call_json(client, model: str, system_instruction: str, prompt: str, schema, temperature: float = 0.2):
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
        await asyncio.sleep(2.0 * (2 ** attempt))
    return None


async def _synthesize_multihop_tier(
    client,
    model: str,
    org_id: int,
    org_name: str,
    content_version: int,
    bundles: List[List[Dict[str, Any]]],
    difficulty: str,
    cluster: str,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    languages = ["English", "Tagalog", "Taglish"]
    
    for idx, bundle in enumerate(bundles, start=1):
        language = languages[idx % len(languages)]
        sys_inst = _build_multihop_instruction(org_name, difficulty, language)
        
        blocks = [
            f"--- CHUNK {i + 1} (ID: {c['chunk_id']}, URL: {c['source_url']}, Campus: {c['campus']}) ---\n{c['content']}"
            for i, c in enumerate(bundle)
        ]
        prompt = "\n\n".join(blocks)
        parsed = await _call_json(client, model, sys_inst, prompt, MultiHopQAPair, temperature=0.25)
        
        if not parsed:
            q_fallback = (
                f"How do the requirements or details in {bundle[0]['heading_path'] or bundle[0]['source_url']} "
                f"compare and combine with {bundle[-1]['heading_path'] or bundle[-1]['source_url']}?"
            )
            a_fallback = "\n\n".join(c["content"] for c in bundle)
            parsed = {
                "query": q_fallback,
                "ground_truth_answer": a_fallback,
                "difficulty": difficulty,
                "reasoning_type": f"{difficulty}_multi_chunk",
            }
            
        req_ids = [int(c["chunk_id"]) for c in bundle]
        primary = bundle[0]
        records.append({
            "test_id": f"org{org_id}_syn100_{cluster[:4]}_{difficulty}_{idx}",
            "set_name": "synthetic_100",
            "domain_cluster": cluster,
            "difficulty": difficulty,
            "reasoning_type": parsed.get("reasoning_type", difficulty),
            "answerable": True,
            "has_ground_truth": True,
            "org_id": org_id,
            "org_name": org_name,
            "content_version": content_version,
            "user_query": parsed["query"].strip(),
            "base_user_query": parsed["query"].strip(),
            "blind_user_query": None,
            "ground_truth_answer": parsed["ground_truth_answer"].strip(),
            "primary_chunk_id": req_ids[0],
            "required_chunk_ids": req_ids,
            "ground_truth_chunk_ids": req_ids,
            "ground_truth_contexts": [c["content"] for c in bundle],
            "ground_truth_content_sha": content_sha(primary["content"]),
            "ground_truth_section_id": primary["section_id"],
            "source_url": primary["source_url"],
            "heading_path": " | ".join(filter(None, [c["heading_path"] for c in bundle])),
            "campus": primary["campus"],
            "academic_level": primary["academic_level"],
            "doc_period": primary["doc_period"],
        })
        await asyncio.sleep(0.3)
    return records


async def build_all_datasets(org_id: int, args) -> None:
    d = tenant_dir(org_id, create=True)
    out_syn_100 = d / args.filename
    out_faqs_21 = d / args.faq_output
    out_real_71 = d / args.real_user_output

    if out_syn_100.exists() and not args.overwrite:
        raise SystemExit(f"{out_syn_100} exists. Use --overwrite to regenerate.")

    async with async_session() as session:
        org = await session.get(Org, org_id)
        org_name = org.name if org else "mseuf"
        content_version = int(org.content_version) if org else 1

    # -------------------------------------------------------------------------
    # PART 1: Build the 100 Synthetic QA Pairs from the 259-pair ground_truth.jsonl
    # -------------------------------------------------------------------------
    src_syn_path = d / args.source_synthetic
    if not src_syn_path.exists():
        raise FileNotFoundError(f"Source 259-pair file not found at {src_syn_path}")
    syn_259 = [r for r in read_jsonl(src_syn_path) if r.get("answerable", True)]
    unique_chunks = _extract_unique_chunks_from_259(syn_259)
    print(f"Loaded {len(syn_259)} synthetic QA pairs ({len(unique_chunks)} unique chunks) from {src_syn_path.name}")

    api_key = settings.llm_qgen_api_key or settings.llm_qa_api_key
    client = genai.Client(api_key=api_key)

    final_100: List[Dict[str, Any]] = []
    for cluster, tier_counts in SYNTHETIC_100_PLAN.items():
        # 1. Easy (Single-hop from 259 pool)
        easy_items = _stratified_select_easy(syn_259, cluster, tier_counts["easy"])
        final_100.extend(easy_items)

        # 2. Medium (Cross-referencing 2-3 chunks, Multilingual)
        med_bundles = _bundle_chunks(unique_chunks, cluster, tier_counts["medium"], group_size=2, prefer_numeric=False)
        print(f"  [Synthetic 100 | {cluster}] Generating {tier_counts['medium']} MEDIUM (2-chunk cross-ref) pairs in English/Tagalog/Taglish...")
        med_items = await _synthesize_multihop_tier(
            client, args.curator_model, org_id, org_name, content_version, med_bundles, "medium", cluster
        )
        final_100.extend(med_items)

        # 3. Hard (Multi-hop / aggregation / calculation across 2-3 chunks, Multilingual)
        hard_bundles = _bundle_chunks(unique_chunks, cluster, tier_counts["hard"], group_size=3, prefer_numeric=True)
        print(f"  [Synthetic 100 | {cluster}] Generating {tier_counts['hard']} HARD (3-chunk multi-hop/calc) pairs in English/Tagalog/Taglish...")
        hard_items = await _synthesize_multihop_tier(
            client, args.curator_model, org_id, org_name, content_version, hard_bundles, "hard", cluster
        )
        final_100.extend(hard_items)

    final_100 = final_100[:100]
    for i, r in enumerate(final_100, start=1):
        r["benchmark_index"] = i
    write_jsonl(out_syn_100, final_100)

    # -------------------------------------------------------------------------
    # PART 2: Curate & Hydrate the 21 Official FAQ QA Pairs (Base queries remain English)
    # -------------------------------------------------------------------------
    src_faq_path = d / args.source_faqs
    faqs_21: List[Dict[str, Any]] = []
    if src_faq_path.exists():
        raw_faqs = read_jsonl(src_faq_path)[:21]
        for idx, r in enumerate(raw_faqs, start=1):
            cids = [int(x) for x in (r.get("ground_truth_chunk_ids") or []) if x is not None]
            if not cids and r.get("ground_truth_contexts"):
                cids = await resolve_chunk_ids_for_texts(org_id, r["ground_truth_contexts"], r.get("source_url"))
            item = dict(r)
            item["test_id"] = f"org{org_id}_faq_{idx}"
            item["set_name"] = "faqs_21"
            item["domain_cluster"] = "faqs_procedures"
            item["difficulty"] = "easy"
            item["answerable"] = True
            item["has_ground_truth"] = True
            item["base_user_query"] = r["user_query"].strip()
            item["blind_user_query"] = None
            item["primary_chunk_id"] = cids[0] if cids else None
            item["required_chunk_ids"] = cids[:1] if cids else []
            item["ground_truth_chunk_ids"] = cids
            if item.get("ground_truth_contexts"):
                item["ground_truth_content_sha"] = content_sha(item["ground_truth_contexts"][0])
            faqs_21.append(item)
        write_jsonl(out_faqs_21, faqs_21)

    # -------------------------------------------------------------------------
    # PART 3: Prepare the 71 Real-User Queries (No generation changes, kept exactly as typed)
    # -------------------------------------------------------------------------
    src_real_path = d / args.source_real_users
    real_71: List[Dict[str, Any]] = []
    if src_real_path.exists():
        raw_real = read_jsonl(src_real_path)[:71]
        for idx, r in enumerate(raw_real, start=1):
            q_text = (r.get("user_query") or "").strip()
            if not q_text:
                continue
            real_71.append({
                "test_id": f"org{org_id}_real_user_{idx}",
                "set_name": "real_user_71",
                "domain_cluster": "real_user",
                "difficulty": "unlabeled",
                "answerable": True,
                "has_ground_truth": False,
                "org_id": org_id,
                "org_name": org_name,
                "content_version": content_version,
                "user_query": q_text,
                "base_user_query": q_text,
                "blind_user_query": None,
                "ground_truth_answer": None,
                "primary_chunk_id": None,
                "required_chunk_ids": [],
                "ground_truth_chunk_ids": [],
                "ground_truth_contexts": [],
                "source_url": None,
            })
        write_jsonl(out_real_71, real_71)

    meta = {
        "org_id": org_id,
        "org_name": org_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "datasets_built": {
            "synthetic_100": len(final_100),
            "faqs_21": len(faqs_21),
            "real_user_71": len(real_71),
            "grand_total": len(final_100) + len(faqs_21) + len(real_71),
        },
        "synthetic_100_by_cluster": {
            cl: sum(1 for r in final_100 if r["domain_cluster"] == cl)
            for cl in ("faqs_procedures", "specs_programs", "policies_announcements")
        },
        "synthetic_100_by_difficulty": {
            df: sum(1 for r in final_100 if r["difficulty"] == df)
            for df in ("easy", "medium", "hard")
        },
        "curator_model": args.curator_model,
        "active_collection": settings.resolved_collection_name,
        "embedding_model": settings.embedding_model,
    }
    out_syn_100.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("\n" + "=" * 70)
    print(f"BENCHMARK SUITE BUILT FOR {org_name.upper()} (100 + 21 + 71 = {meta['datasets_built']['grand_total']} entries)")
    print(f"  1. Synthetic 100 : {out_syn_100.name} -> {meta['synthetic_100_by_difficulty']} | {meta['synthetic_100_by_cluster']}")
    print(f"  2. Official FAQs : {out_faqs_21.name} -> {len(faqs_21)} entries")
    print(f"  3. Real Users    : {out_real_71.name} -> {len(real_71)} entries (no-GT evaluation)")
    print("=" * 70)


def main() -> None:
    p = argparse.ArgumentParser(description="Structure 100 synthetic + 21 FAQ + 71 real-user benchmark datasets.")
    p.add_argument("--org-id", type=int, default=1)
    p.add_argument("--source-synthetic", default="ground_truth.jsonl", help="Input 259-pair synthetic JSONL")
    p.add_argument("--source-faqs", default="ground_truth_faqs.jsonl", help="Input official FAQs JSONL")
    p.add_argument("--source-real-users", default="queries_real_users.jsonl", help="Input 71 real-user queries JSONL")
    p.add_argument("--filename", default="ground_truth_100.jsonl", help="Output 100-entry structured synthetic JSONL")
    p.add_argument("--faq-output", default="ground_truth_faqs_21.jsonl", help="Output 21-entry official FAQs JSONL")
    p.add_argument("--real-user-output", default="queries_real_users_71.jsonl", help="Output 71-entry real users JSONL")
    p.add_argument("--curator-model", default=DEFAULT_CURATOR_MODEL)
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()

    install_postgres_write_guard()
    asyncio.run(build_all_datasets(args.org_id, args))


if __name__ == "__main__":
    main()