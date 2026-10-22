"""Turns a CSV of HUMAN-written questions into a labelled test set (set_name = "human").

CSV columns (header required):
  query            - the question exactly as a real person would type it            (required)
  gold_phrase      - 6-15 words copied verbatim from the page that answers it        (use this OR gold_chunk_id)
  gold_chunk_id    - Postgres chunks.id of the answering chunk                        (use this OR gold_phrase)
  reference_answer - short correct answer, written by you from the website           (optional; enables answer metrics)

Why gold_phrase: you read the official site, copy a distinctive sentence fragment, and we find the chunk(s) containing it.
No retrieval system is involved in choosing the gold chunk, so there is no circularity.

Usage:  uv run python -m evaluation.import_human_queries --org-id 1 --csv path/to/queries.csv
"""
import argparse
import asyncio
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session
from app.models.chunk import Chunk
from app.models.org import Org
from app.models.scraped_page import PageProcessStatus, ScrapedPage
from app.services.ingest_pipeline.orchestrator import extract_sub_entity_from_url
from evaluation.common import content_sha, normalize_ws, tenant_dir, write_jsonl
from evaluation.safety import install_postgres_write_guard


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--org-id", type=int, required=True)
    p.add_argument("--csv", required=True)
    p.add_argument("--filename", default="ground_truth_human.jsonl")
    args = p.parse_args()

    install_postgres_write_guard()
    async with async_session() as session:
        org = await session.get(Org, args.org_id)
        if not org:
            raise SystemExit(f"Org {args.org_id} not found")
        rows = (
            await session.execute(
                select(Chunk.id, Chunk.content, Chunk.section_id, Chunk.heading_path, ScrapedPage.url)
                .join(ScrapedPage, Chunk.page_id == ScrapedPage.id)
                .where(ScrapedPage.org_id == args.org_id, ScrapedPage.status == PageProcessStatus.COMPLETED)
            )
        ).all()
    by_id = {int(r.id): r for r in rows}
    norm = {int(r.id): normalize_ws(r.content) for r in rows}

    out: List[Dict[str, Any]] = []
    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f), start=1):
            q = (row.get("query") or "").strip()
            if not q:
                continue
            gold_ids: List[int] = []
            if (row.get("gold_chunk_id") or "").strip():
                gold_ids = [int(row["gold_chunk_id"])]
            elif (row.get("gold_phrase") or "").strip():
                phrase = normalize_ws(row["gold_phrase"])
                gold_ids = [cid for cid, txt in norm.items() if phrase in txt]
            if not gold_ids or any(g not in by_id for g in gold_ids):
                print(f"[Row {n}] SKIPPED, no chunk found for gold label: {q[:60]!r}")
                continue
            shas = {content_sha(by_id[g].content) for g in gold_ids}
            if len(shas) > 1:
                print(f"[Row {n}] WARNING phrase matches {len(shas)} DIFFERENT chunks {gold_ids}; keeping all as gold. Tighten the phrase if wrong.")
            primary = gold_ids[0]
            r = by_id[primary]
            ref = (row.get("reference_answer") or "").strip() or None
            out.append({
                "test_id": f"org{args.org_id}_human{n}", "set_name": "human", "answerable": True,
                "org_id": args.org_id, "org_name": org.name, "content_version": org.content_version,
                "user_query": q, "ground_truth_answer": ref, "primary_chunk_id": primary,
                "ground_truth_chunk_ids": gold_ids, "ground_truth_contexts": [r.content],
                "ground_truth_content_sha": content_sha(r.content), "ground_truth_section_id": r.section_id or "",
                "source_url": r.url, "heading_path": r.heading_path or "",
                "campus": extract_sub_entity_from_url(r.url),
            })
    path = tenant_dir(args.org_id, create=True) / args.filename
    n = write_jsonl(path, out)
    print(f"Wrote {n} human-labelled records to {path.resolve()} "
          f"({sum(1 for r in out if r['ground_truth_answer']) } with reference answers).")


if __name__ == "__main__":
    asyncio.run(main())
