"""Builds and structures the evaluation datasets (150 + 63 + 71 = 284 total entries).
READ-ONLY on Postgres (SELECTs only); writes local files under evaluation/data/org_<id>/.

Datasets built:
  1. `ground_truth_150.jsonl`: Formulates EXACTLY 150 synthetic QA pairs from `ground_truth.jsonl`,
     split into EXACTLY 50 English, 50 Tagalog, and 50 Taglish queries, balanced across 3 domain clusters
     (`faqs_procedures`: 51, `specs_programs`: 50, `policies_announcements`: 49) and 3 difficulty tiers:
       - Easy   (60 entries): Single-hop (1 chunk) in English (20), Tagalog (20), Taglish (20)
       - Medium (51 entries): Cross-referencing 2-3 chunks in English (17), Tagalog (17), Taglish (17)
       - Hard   (39 entries): Multi-hop / calculation across 2-3 chunks in English (13), Tagalog (13), Taglish (13)
  2. `ground_truth_faqs_63.jsonl`: Full 21 official FAQs generated in all 3 languages (21 English, 21 Tagalog,
     21 Taglish = 63 entries total), with their chunk IDs hydrated from PostgreSQL.
  3. `queries_real_users_71.jsonl`: 71 real-user queries (`set_name="real_user_71"`), left untouched.

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

DEFAULT_CURATOR_MODEL = "gemini-3.1-flash-lite"
LANGUAGES = ["English", "Tagalog", "Taglish"]

# Exact 150-entry plan for Synthetic QA pairs (50 English, 50 Tagalog, 50 Taglish total):
#   faqs_procedures        (51 total) = 21 easy + 18 medium + 12 hard
#   specs_programs         (50 total) = 20 easy + 17 medium + 13 hard
#   policies_announcements (49 total) = 19 easy + 16 medium + 14 hard
#   ------------------------------------------------------------------
#   Total                  (150)      = 60 easy + 51 medium + 39 hard
SYNTHETIC_150_PLAN = {
    "faqs_procedures": {"easy": 21, "medium": 18, "hard": 12},
    "specs_programs": {"easy": 20, "medium": 17, "hard": 13},
    "policies_announcements": {"easy": 19, "medium": 16, "hard": 14},
}


class QueryTranslation(BaseModel):
    query: str = Field(description="Realistic standalone user query formulated or translated into the target language.")


class MultiHopQAPair(BaseModel):
    query: str = Field(description="Standalone question requiring all provided chunks to answer completely, in the target language.")
    ground_truth_answer: str = Field(
        description="Complete, strictly grounded reference answer combining/calculating facts across the chunks (in English)."
    )
    difficulty: str = Field(description="'medium' for cross-referencing or 'hard' for calculation/aggregation/multi-hop.")
    reasoning_type: str = Field(description="e.g. 'cross_reference_comparison', 'numeric_aggregation', 'date_duration_calculation'")


def _build_multihop_instruction(org_name: str, difficulty: str, language: str) -> str:
    if difficulty == "medium":
        return f"""You are a Senior RAG Benchmark Architect for {org_name}.
You are given 2 to 3 related document chunks from {org_name}'s knowledge base.
Write ONE realistic user question (strictly written in {language}) and its strictly grounded reference answer (written in English) that REQUIRES cross-referencing facts from AT LEAST TWO of the provided chunks.
Examples of Medium (Cross-Referencing) tasks:
- Comparing document requirements or procedures between two applicant types, programs, or campuses.
- Connecting an office/program mentioned in one chunk with its schedule, requirements, or staff in another chunk.
STRICT RULES:
1. Do NOT invent facts outside the provided chunks.
2. The user query MUST be in {language}.
3. The reference answer MUST be in English.
4. Set difficulty="medium"."""
    return f"""You are a Senior RAG Benchmark Architect for {org_name}.
You are given 2 to 3 related document chunks from {org_name}'s knowledge base.
Write ONE realistic, challenging user question (strictly written in {language}) and its strictly grounded reference answer (written in English) that REQUIRES multi-hop reasoning, counting, numeric aggregation, or date/duration calculation across the chunks.
Examples of Hard (Multi-Hop / Aggregation / Calculation) tasks:
- Calculating total document copies/fees/units if applicants of different levels or programs apply together.
- Counting total qualifiers, awards, or days suspended across multiple announcements/sections.
- Synthesizing multi-step conditional rules across chunks (e.g. prerequisite failures, bridging requirements).
STRICT RULES:
1. Every number, date, and condition in `ground_truth_answer` must be verifiable from the chunks. Show the exact breakdown in `ground_truth_answer`.
2. The user query MUST be in {language}.
3. The reference answer MUST be in English.
4. Set difficulty="hard"."""


async def resolve_chunk_ids_for_texts(
    org_id: int, contexts: List[str], source_url: Optional[str] = None
) -> List[int]:
    """Maps ground_truth_contexts to live SQL Chunk.id values."""
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
    """Extracts unique source chunks from the 259 synthetic pairs."""
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
    start_global_idx: int,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for idx, bundle in enumerate(bundles, start=1):
        language = LANGUAGES[(start_global_idx + idx - 1) % len(LANGUAGES)]
        sys_inst = _build_multihop_instruction(org_name, difficulty, language)
        blocks = [
            f"--- CHUNK {i + 1} (ID: {c['chunk_id']}, URL: {c['source_url']}, Campus: {c['campus']}) ---\n{c['content']}"
            for i, c in enumerate(bundle)
        ]
        prompt = f"Language target: {language}\n\n" + "\n\n".join(blocks)
        parsed = await _call_json(client, model, sys_inst, prompt, MultiHopQAPair, temperature=0.25)
        if not parsed:
            q_fallback = (
                f"How do the requirements in {bundle[0]['heading_path'] or bundle[0]['source_url']} "
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
            "test_id": f"org{org_id}_syn150_{cluster[:4]}_{difficulty}_{idx}",
            "set_name": "synthetic_150",
            "domain_cluster": cluster,
            "difficulty": difficulty,
            "language": language,
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


async def _select_and_rewrite_easy(
    client,
    model: str,
    org_id: int,
    syn_259: List[Dict[str, Any]],
    cluster: str,
    count_needed: int,
    start_global_idx: int,
) -> List[Dict[str, Any]]:
    """Selects single-hop items and ensures exact English, Tagalog, and Taglish rotation."""
    pool = [
        r for r in syn_259
        if infer_domain_cluster(
            r.get("source_url") or "",
            r.get("heading_path") or "",
            (r.get("ground_truth_contexts") or [""])[0],
        ) == cluster
    ]
    by_url: Dict[str, List[Dict[str, Any]]] = {}
    for r in pool:
        by_url.setdefault(r.get("source_url") or "", []).append(r)

    selected: List[Dict[str, Any]] = []
    seen_cids = set()
    queues = [list(v) for v in by_url.values()]
    while queues and len(selected) < count_needed:
        next_q = []
        for q in queues:
            while q and len(selected) < count_needed:
                cand = q.pop(0)
                cid = (cand.get("ground_truth_chunk_ids") or [None])[0]
                if cid not in seen_cids:
                    seen_cids.add(cid)
                    selected.append(cand)
                    break
            if q:
                next_q.append(q)
        queues = next_q

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
        language = LANGUAGES[(start_global_idx + idx - 1) % len(LANGUAGES)]
        base_q = r["user_query"].strip()
        query_text = base_q

        if language in ("Tagalog", "Taglish"):
            sys_inst = (
                f"You are a benchmark rewriter. Rewrite the following English question into natural {language}. "
                "Keep all specific names, degrees, and requirements accurate. Output valid JSON."
            )
            prompt = f"Original English Query: {base_q}\nTarget Language: {language}"
            parsed = await _call_json(client, model, sys_inst, prompt, QueryTranslation, temperature=0.3)
            if parsed and parsed.get("query"):
                query_text = parsed["query"].strip()

        cids = [int(x) for x in (r.get("ground_truth_chunk_ids") or []) if x is not None]
        ctxs = r.get("ground_truth_contexts") or []
        item = dict(r)
        item["test_id"] = f"org{r.get('org_id', org_id)}_syn150_{cluster[:4]}_easy_{idx}"
        item["set_name"] = "synthetic_150"
        item["domain_cluster"] = cluster
        item["difficulty"] = "easy"
        item["language"] = language
        item["reasoning_type"] = "single_hop"
        item["answerable"] = True
        item["has_ground_truth"] = True
        item["user_query"] = query_text
        item["base_user_query"] = query_text
        item["blind_user_query"] = None
        item["primary_chunk_id"] = cids[0] if cids else None
        item["required_chunk_ids"] = cids[:1]
        item["ground_truth_chunk_ids"] = cids
        if ctxs:
            item["ground_truth_content_sha"] = content_sha(ctxs[0])
        out.append(item)
        await asyncio.sleep(0.2)

    return out


async def build_63_multilingual_faqs(
    client, model: str, org_id: int, raw_faqs_21: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Builds a full 21 English, 21 Tagalog, and 21 Taglish FAQ dataset (63 entries total)."""
    faqs_63: List[Dict[str, Any]] = []

    for lang_code in LANGUAGES:
        for idx, r in enumerate(raw_faqs_21, start=1):
            base_eng_query = r["user_query"].strip()
            query_text = base_eng_query

            if lang_code in ("Tagalog", "Taglish"):
                sys_inst = (
                    f"You are an expert translator for official university FAQs. Translate the following official admission "
                    f"FAQ question into natural, conversational {lang_code}. Keep it direct and natural. Output valid JSON."
                )
                prompt = f"Official Question: {base_eng_query}\nTarget Language: {lang_code}"
                parsed = await _call_json(client, model, sys_inst, prompt, QueryTranslation, temperature=0.2)
                if parsed and parsed.get("query"):
                    query_text = parsed["query"].strip()

            cids = [int(x) for x in (r.get("ground_truth_chunk_ids") or []) if x is not None]
            if not cids and r.get("ground_truth_contexts"):
                cids = await resolve_chunk_ids_for_texts(org_id, r["ground_truth_contexts"], r.get("source_url"))

            item = dict(r)
            item["test_id"] = f"org{org_id}_faq_{lang_code.lower()}_{idx}"
            item["set_name"] = "faqs_63"
            item["domain_cluster"] = "faqs_procedures"
            item["difficulty"] = "easy"
            item["language"] = lang_code
            item["answerable"] = True
            item["has_ground_truth"] = True
            item["user_query"] = query_text
            item["base_user_query"] = query_text
            item["blind_user_query"] = None
            item["primary_chunk_id"] = cids[0] if cids else None
            item["required_chunk_ids"] = cids[:1] if cids else []
            item["ground_truth_chunk_ids"] = cids
            if item.get("ground_truth_contexts"):
                item["ground_truth_content_sha"] = content_sha(item["ground_truth_contexts"][0])
            faqs_63.append(item)
            await asyncio.sleep(0.15)

    return faqs_63


async def build_all_datasets(org_id: int, args) -> None:
    d = tenant_dir(org_id, create=True)
    out_syn_150 = d / args.filename
    out_faqs_63 = d / args.faq_output
    out_real_71 = d / args.real_user_output

    if out_syn_150.exists() and not args.overwrite:
        raise SystemExit(f"{out_syn_150} exists. Use --overwrite to regenerate.")

    async with async_session() as session:
        org = await session.get(Org, org_id)
        org_name = org.name if org else "mseuf"
        content_version = int(org.content_version) if org else 1

    api_key = settings.llm_qgen_api_key or settings.llm_qa_api_key
    client = genai.Client(api_key=api_key)

    # -------------------------------------------------------------------------
    # PART 1: Build the 150 Synthetic QA Pairs (50 English, 50 Tagalog, 50 Taglish)
    # -------------------------------------------------------------------------
    src_syn_path = d / args.source_synthetic
    if not src_syn_path.exists():
        raise FileNotFoundError(f"Source 259-pair file not found at {src_syn_path}")
    syn_259 = [r for r in read_jsonl(src_syn_path) if r.get("answerable", True)]
    unique_chunks = _extract_unique_chunks_from_259(syn_259)
    print(f"Loaded {len(syn_259)} synthetic QA pairs ({len(unique_chunks)} unique chunks) from {src_syn_path.name}")

    final_150: List[Dict[str, Any]] = []
    global_lang_counter = 0

    for cluster, tier_counts in SYNTHETIC_150_PLAN.items():
        print(f"  [Synthetic 150 | {cluster}] Curating {tier_counts['easy']} EASY queries (English/Tagalog/Taglish)...")
        easy_items = await _select_and_rewrite_easy(
            client, args.curator_model, org_id, syn_259, cluster, tier_counts["easy"], global_lang_counter
        )
        final_150.extend(easy_items)
        global_lang_counter += len(easy_items)

        med_bundles = _bundle_chunks(unique_chunks, cluster, tier_counts["medium"], group_size=2, prefer_numeric=False)
        print(f"  [Synthetic 150 | {cluster}] Generating {tier_counts['medium']} MEDIUM pairs (English/Tagalog/Taglish)...")
        med_items = await _synthesize_multihop_tier(
            client, args.curator_model, org_id, org_name, content_version, med_bundles, "medium", cluster, global_lang_counter
        )
        final_150.extend(med_items)
        global_lang_counter += len(med_items)

        hard_bundles = _bundle_chunks(unique_chunks, cluster, tier_counts["hard"], group_size=3, prefer_numeric=True)
        print(f"  [Synthetic 150 | {cluster}] Generating {tier_counts['hard']} HARD pairs (English/Tagalog/Taglish)...")
        hard_items = await _synthesize_multihop_tier(
            client, args.curator_model, org_id, org_name, content_version, hard_bundles, "hard", cluster, global_lang_counter
        )
        final_150.extend(hard_items)
        global_lang_counter += len(hard_items)

    final_150 = final_150[:150]
    for i, r in enumerate(final_150, start=1):
        r["benchmark_index"] = i
    write_jsonl(out_syn_150, final_150)

    # -------------------------------------------------------------------------
    # PART 2: Build the Full 63 Official FAQs (21 English, 21 Tagalog, 21 Taglish)
    # -------------------------------------------------------------------------
    src_faq_path = d / args.source_faqs
    faqs_63: List[Dict[str, Any]] = []
    if src_faq_path.exists():
        raw_faqs_21 = read_jsonl(src_faq_path)[:21]
        print(f"\nBuilding 63 multilingual FAQs (21 English, 21 Tagalog, 21 Taglish) from {src_faq_path.name}...")
        faqs_63 = await build_63_multilingual_faqs(client, args.curator_model, org_id, raw_faqs_21)
        write_jsonl(out_faqs_63, faqs_63)

    # -------------------------------------------------------------------------
    # PART 3: Prepare the 71 Real-User Queries (Untouched)
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

    syn_langs = {lang: sum(1 for r in final_150 if r.get("language") == lang) for lang in LANGUAGES}
    faq_langs = {lang: sum(1 for r in faqs_63 if r.get("language") == lang) for lang in LANGUAGES}

    meta = {
        "org_id": org_id,
        "org_name": org_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "datasets_built": {
            "synthetic_150": len(final_150),
            "faqs_63": len(faqs_63),
            "real_user_71": len(real_71),
            "grand_total": len(final_150) + len(faqs_63) + len(real_71),
        },
        "synthetic_150_by_language": syn_langs,
        "faqs_63_by_language": faq_langs,
        "synthetic_150_by_difficulty": {
            df: sum(1 for r in final_150 if r["difficulty"] == df)
            for df in ("easy", "medium", "hard")
        },
        "curator_model": args.curator_model,
        "active_collection": settings.resolved_collection_name,
        "embedding_model": settings.embedding_model,
    }
    out_syn_150.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("\n" + "=" * 75)
    print(f"BENCHMARK SUITE BUILT FOR {org_name.upper()} (Grand Total: {meta['datasets_built']['grand_total']} queries)")
    print(f"  1. Synthetic 150 : {out_syn_150.name} -> Languages: {syn_langs} | Tiers: {meta['synthetic_150_by_difficulty']}")
    print(f"  2. Official FAQs : {out_faqs_63.name} -> {len(faqs_63)} total ({faq_langs})")
    print(f"  3. Real Users    : {out_real_71.name} -> {len(real_71)} entries (unlabeled real queries)")
    print("=" * 75)


def main() -> None:
    p = argparse.ArgumentParser(description="Structure 150 synthetic (50 each) + 63 FAQ (21 each) + 71 real-user datasets.")
    p.add_argument("--org-id", type=int, default=1)
    p.add_argument("--source-synthetic", default="ground_truth.jsonl")
    p.add_argument("--source-faqs", default="ground_truth_faqs.jsonl")
    p.add_argument("--source-real-users", default="queries_real_users.jsonl")
    p.add_argument("--filename", default="ground_truth_150.jsonl")
    p.add_argument("--faq-output", default="ground_truth_faqs_63.jsonl")
    p.add_argument("--real-user-output", default="queries_real_users_71.jsonl")
    p.add_argument("--curator-model", default=DEFAULT_CURATOR_MODEL)
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()

    install_postgres_write_guard()
    asyncio.run(build_all_datasets(args.org_id, args))


if __name__ == "__main__":
    main()