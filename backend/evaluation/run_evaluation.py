"""Full evaluation runner (READ-ONLY against production).

  uv run python -m evaluation.run_evaluation --org-id 1 --stage retrieval          # fast, cheap, no answer generation
  uv run python -m evaluation.run_evaluation --org-id 1 --stage all --top-k 5       # + answers, judges, Ragas, abstention

Outputs go to backend/evaluation/data/org_<id>/runs/<timestamp>/  (rows.jsonl, rows.csv, summary.json, report.md, config.json)
Nothing is overwritten between runs.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import evaluation.compat  # noqa: E402,F401  (must run before ragas/langchain/aiohttp are imported)

import argparse  # noqa: E402
import asyncio  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import async_session  # noqa: E402
from app.models.chunk import Chunk  # noqa: E402
from evaluation.common import (  # noqa: E402
    EVAL_DIR, content_sha, load_dataset_meta, normalize_record, read_jsonl, tenant_dir,
)
from evaluation.custom_judges import run_abstention_judges, run_answer_judges  # noqa: E402
from evaluation.pipeline_inspector import execute_instrumented_query  # noqa: E402
from evaluation.reporting import headline, render_markdown, summarize  # noqa: E402
from evaluation.safety import (  # noqa: E402
    build_safe_pipeline, require_safe_environment, selftest_postgres_guard,
)
from evaluation.traditional_metrics import (  # noqa: E402
    compute_all_lexical_metrics, first_rank, first_url_rank, gold_in_contexts,
)

DEFAULT_JUDGE_MODEL = "gemini-3.8-flash"
SET_ALIASES = {"standard": "synthetic_standard", "colloquial": "synthetic_colloquial",
               "negative": "negative", "human": "human"}


# --------------------------------------------------------------------------------------
# Dataset loading
# --------------------------------------------------------------------------------------

def resolve_filenames(org_id: int, requested: Optional[List[str]]) -> List[str]:
    if requested:
        return requested
    d = tenant_dir(org_id)
    return ["ground_truth_v2.jsonl"] if (d / "ground_truth_v2.jsonl").exists() else ["ground_truth.jsonl"]


def load_records(org_id: int, filenames: List[str], sets: Optional[List[str]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for fn in filenames:
        path = tenant_dir(org_id) / fn
        if not path.exists():
            raise FileNotFoundError(f"{path} not found. Run evaluation.generate_ground_truth / import_human_queries first.")
        meta = load_dataset_meta(path)
        if meta:
            if meta.get("active_collection") and meta["active_collection"] != settings.resolved_collection_name:
                print(f"[WARN] {fn}: generated against collection {meta['active_collection']!r}, now {settings.resolved_collection_name!r}")
            if meta.get("embedding_model") and meta["embedding_model"] != settings.embedding_model:
                print(f"[WARN] {fn}: generated with embedding model {meta['embedding_model']!r}, now {settings.embedding_model!r}")
        records += [normalize_record(r) for r in read_jsonl(path)]
    if sets:
        wanted = {SET_ALIASES.get(s, s) for s in sets}
        records = [r for r in records if r["set_name"] in wanted]
    return records


async def drop_stale(records: List[Dict[str, Any]]):
    """A record is stale if its gold chunk was re-scraped (content changed) or deleted after the dataset was made."""
    ids = sorted({int(r["primary_chunk_id"]) for r in records if r["answerable"] and r["primary_chunk_id"] is not None})
    current: Dict[int, str] = {}
    if ids:
        async with async_session() as session:
            rows = (await session.execute(select(Chunk.id, Chunk.content).where(Chunk.id.in_(ids)))).all()
        current = {int(i): content_sha(c) for i, c in rows}
    fresh, stale = [], []
    for r in records:
        if not r["answerable"]:
            fresh.append(r)
            continue
        pid = r["primary_chunk_id"]
        sha = r.get("ground_truth_content_sha")
        if pid is None or int(pid) not in current or (sha and current[int(pid)] != sha):
            stale.append(r)
        else:
            fresh.append(r)
    return fresh, stale


def cap_per_set(records: List[Dict[str, Any]], max_samples: Optional[int]) -> List[Dict[str, Any]]:
    if not max_samples or max_samples <= 0:
        return records
    counts: Dict[str, int] = {}
    out = []
    for r in records:
        counts[r["set_name"]] = counts.get(r["set_name"], 0) + 1
        if counts[r["set_name"]] <= max_samples:
            out.append(r)
    return out


# --------------------------------------------------------------------------------------
# Scoring one query
# --------------------------------------------------------------------------------------

def build_row(rec: Dict[str, Any], res, k: int, answer_stage: bool) -> Dict[str, Any]:
    gold = rec["ground_truth_chunk_ids"]
    answerable = bool(rec["answerable"])
    texts = [c.content for c in res.expanded_contexts]
    urls = [c.source_url for c in res.expanded_contexts if c.source_url]

    def ids(cands):
        return [c.sql_chunk_id for c in cands]

    row: Dict[str, Any] = {
        "test_id": rec["test_id"], "set_name": rec["set_name"], "answerable": answerable,
        "negative_kind": rec.get("negative_kind"), "needs_review": rec.get("needs_review"),
        "cluster": rec["primary_chunk_id"] if (answerable and rec["primary_chunk_id"] is not None) else rec["test_id"],
        "org_id": rec.get("org_id"), "campus": rec.get("campus"), "user_input": rec["user_query"],
        "reference": rec.get("ground_truth_answer"), "gt_url": rec.get("source_url"), "n_gold_equivalents": len(gold),
        "source": res.source, "fallback_reason": res.fallback_reason, "detected_campus": res.detected_campus,
        "response": res.answer, "retrieved_urls": urls, "answer_stage": answer_stage,
        "top_rerank_score": res.post_rerank_candidates[0].score if res.post_rerank_candidates else None,
        "latency_ms": res.latency_ms, "retrieval_latency_ms": res.retrieval_latency_ms, "_contexts": texts,
    }
    if answerable and gold:
        row["rank_dense"] = first_rank(res.dense_chunk_order, gold)
        row["rank_sparse"] = first_rank(res.sparse_chunk_order, gold)
        row["rank_rrf"] = first_rank(ids(res.pre_rerank_candidates), gold)
        row["rank_rerank"] = first_rank(ids(res.post_rerank_candidates), gold)
        row["rank_final"] = first_rank(ids(res.final_reranked_candidates), gold)
        row["url_rank_final_diagnostic"] = first_url_rank([c.source_url for c in res.final_reranked_candidates], rec.get("source_url"))
        row["ctx_hit"], row["ctx_rank"] = (gold_in_contexts(rec["ground_truth_contexts"][0], texts)
                                           if rec["ground_truth_contexts"] else (False, None))
    return row


# --------------------------------------------------------------------------------------
# Answer stage (judges + Ragas + lexical)
# --------------------------------------------------------------------------------------

def setup_ragas_judge(judge_model_name: str):
    from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import answer_correctness, answer_relevancy, context_precision, context_recall, faithfulness

    api_key = settings.llm_qa_api_key or settings.llm_qgen_api_key
    os.environ["GOOGLE_API_KEY"] = api_key
    judge_llm = ChatGoogleGenerativeAI(model=judge_model_name, temperature=0.0, google_api_key=api_key)
    emb_model = getattr(settings, "embedding_model", None) or "gemini-embedding-2"
    if not emb_model.startswith("models/"):
        emb_model = f"models/{emb_model}"
    judge_emb = GoogleGenerativeAIEmbeddings(model=emb_model, google_api_key=api_key)
    wrapped_llm, wrapped_emb = LangchainLLMWrapper(judge_llm), LangchainEmbeddingsWrapper(judge_emb)
    metrics = [context_precision, context_recall, faithfulness, answer_relevancy, answer_correctness]
    for m in metrics:
        m.llm = wrapped_llm
        if hasattr(m, "embeddings"):
            m.embeddings = wrapped_emb
    return metrics


def run_ragas(rows: List[Dict[str, Any]], judge_model: str) -> None:
    import pandas as pd
    from datasets import Dataset
    from ragas import evaluate

    metrics = setup_ragas_judge(judge_model)
    df = pd.DataFrame([{"user_input": r["user_input"], "retrieved_contexts": r["_contexts"] or ["No context retrieved."],
                        "response": r["response"], "reference": r["reference"]} for r in rows])
    scores = evaluate(dataset=Dataset.from_pandas(df), metrics=metrics).to_pandas()
    for i, r in enumerate(rows):
        for col in ("context_precision", "context_recall", "faithfulness", "answer_relevancy", "answer_correctness"):
            if col in scores.columns:
                v = scores[col].iloc[i]
                r[col] = None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)


async def run_answer_stage(rows: List[Dict[str, Any]], judge_model: str, skip_ragas: bool) -> Dict[str, Any]:
    answerable = [r for r in rows if r["answerable"] and r["source"] == "llm" and r.get("reference")]
    neg = [r for r in rows if not r["answerable"]]
    info = {"judge_failures": 0, "abstention_judge_failures": 0, "ragas_error": None}

    for r in answerable:
        r.update(compute_all_lexical_metrics(prediction=r["response"], reference=r["reference"]))

    print(f"[Answer stage] custom judges on {len(answerable)} answered rows ({judge_model}) ...")
    inputs = [{"test_id": r["test_id"], "user_input": r["user_input"], "reference": r["reference"],
               "retrieved_contexts": r["_contexts"] or ["No context retrieved."], "response": r["response"]} for r in answerable]
    scores, failed = await run_answer_judges(inputs, judge_model)
    info["judge_failures"] = failed
    for r in answerable:
        r.update(scores.get(r["test_id"], {}))

    for r in neg:
        if r["source"] == "fallback":
            r["abstained"], r["asserted_unsupported_facts"] = True, False
    to_judge = [{"test_id": r["test_id"], "user_input": r["user_input"],
                 "retrieved_contexts": r["_contexts"] or ["No context retrieved."], "response": r["response"]}
                for r in neg if r["source"] == "llm"]
    if to_judge:
        print(f"[Answer stage] abstention judge on {len(to_judge)} negative rows ...")
        verdicts, f2 = await run_abstention_judges(to_judge, judge_model)
        info["abstention_judge_failures"] = f2
        for r in neg:
            if r["test_id"] in verdicts:
                r.update(verdicts[r["test_id"]])

    if skip_ragas or not answerable:
        return info
    print(f"[Answer stage] Ragas on {len(answerable)} rows ...")
    try:
        run_ragas(answerable, judge_model)
    except Exception as e:  # noqa: BLE001
        info["ragas_error"] = repr(e)
        print(f"[Ragas ERROR] {e!r}. Retrieval + custom-judge results are still saved.")
    return info


# --------------------------------------------------------------------------------------
# Parity check: does the inspector still equal production?
# --------------------------------------------------------------------------------------

async def run_parity_check(pipeline, org_id: int, records: List[Dict[str, Any]], k: int, n: int) -> str:
    from app.services.query_pipeline.schema import PipelineQueryRequest

    sample = [r for r in records if r["answerable"]][:n]
    same = 0
    for r in sample:
        prod = await pipeline.execute(PipelineQueryRequest(query=r["user_query"], org_id=org_id, top_k=k))
        mine = await execute_instrumented_query(pipeline, org_id, r["user_query"], k, generate_answer=False)
        if [c.content for c in prod.contexts] == [c.content for c in mine.expanded_contexts]:
            same += 1
        else:
            print(f"  [Parity MISMATCH] {r['test_id']}: production returned {len(prod.contexts)} contexts, inspector {len(mine.expanded_contexts)}")
    msg = f"{same}/{len(sample)} identical"
    print(f"[Parity] {msg}")
    if sample and same == 0:
        raise SystemExit("Parity check failed for every sampled query: the inspector no longer mirrors production. Stop and fix pipeline_inspector.py.")
    return msg


# --------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------

def write_outputs(run_dir: Path, rows: List[Dict[str, Any]], summary: Dict[str, Any], md: str, config: Dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "rows.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    flat = [{k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in r.items() if k != "_contexts"} for r in rows]
    fields: List[str] = []
    for r in flat:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(run_dir / "rows.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(flat)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (run_dir / "report.md").write_text(md, encoding="utf-8")
    (run_dir / "config.json").write_text(json.dumps(config, indent=2, default=str), encoding="utf-8")


# --------------------------------------------------------------------------------------
# Per-tenant flow
# --------------------------------------------------------------------------------------

async def evaluate_tenant(pipeline, org_id: int, args, env: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    answer_stage = args.stage in ("answer", "all")
    filenames = resolve_filenames(org_id, args.filename)
    records = load_records(org_id, filenames, args.sets)
    records, stale = await drop_stale(records)
    records = cap_per_set(records, args.max_samples)
    if not records:
        print(f"[Skip] no usable records for org_{org_id}.")
        return None
    org_name = records[0].get("org_name", f"Org {org_id}")

    counts: Dict[str, int] = {}
    for r in records:
        counts[r["set_name"]] = counts.get(r["set_name"], 0) + 1
    print("\n" + "=" * 78)
    print(f"EVALUATING {org_name} (org_id={org_id}) | top_k={args.top_k} | stage={args.stage} | sets={counts} | stale skipped={len(stale)}")
    print("=" * 78)

    parity = None
    if args.parity_check > 0:
        parity = await run_parity_check(pipeline, org_id, records, args.top_k, args.parity_check)

    rows: List[Dict[str, Any]] = []
    errors = 0
    for idx, rec in enumerate(records, start=1):
        res = None
        for attempt in range(3):
            try:
                res = await execute_instrumented_query(pipeline, org_id, rec["user_query"], args.top_k, generate_answer=answer_stage)
                break
            except Exception as e:  # noqa: BLE001
                print(f"  [retry {attempt + 1}/3] {rec['test_id']}: {e!r}")
                await asyncio.sleep(3 * (attempt + 1))
        if res is None:
            errors += 1
            continue
        row = build_row(rec, res, args.top_k, answer_stage)
        rows.append(row)
        print(f"  [{idx}/{len(records)}] {rec['set_name'][:10]:<10} gold@rrf={row.get('rank_rrf')} rerank={row.get('rank_rerank')} "
              f"final={row.get('rank_final')} ctx={row.get('ctx_hit')} src={row['source']} {row['latency_ms']:.0f}ms")
        await asyncio.sleep(args.sleep)
    if errors:
        print(f"[WARN] {errors} queries failed after retries and were excluded (infrastructure errors, not misses).")

    answer_info: Dict[str, Any] = {}
    if answer_stage:
        answer_info = await run_answer_stage(rows, args.judge_model, args.skip_ragas)

    meta = {
        "org_id": org_id, "org_name": org_name, "evaluated_at": datetime.now(timezone.utc).isoformat(), "top_k": args.top_k,
        "n_boot": args.bootstrap, "stage": args.stage, "dataset_files": filenames, "stale_skipped": len(stale),
        "excluded_errors": errors, "parity": parity, "qdrant_collection": env.get("qdrant_collection"),
        "qa_model": env.get("qa_model"), "judge_model": args.judge_model if answer_stage else None,
        "embedding_model": env.get("embedding_model"), "answer_stage_info": answer_info,
        "curator_model": next((load_dataset_meta(tenant_dir(org_id) / f) or {}).get("curator_model") for f in filenames[:1]),
    }
    summary = summarize(rows, args.top_k, n_boot=args.bootstrap, seed=args.seed, meta=meta)
    md = render_markdown(summary, args.top_k)
    run_dir = tenant_dir(org_id, create=True) / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S")
    write_outputs(run_dir, rows, summary, md, {"args": vars(args), "environment": env})
    print("\n" + md)
    print(f"\nSaved run to {run_dir.resolve()}")
    return summary


async def run_all(args) -> None:
    env = require_safe_environment(args.allow_prod_read)
    await selftest_postgres_guard()
    print("[Safety] Postgres write guard self-test passed (a write statement was blocked before reaching the DB).")
    if args.stage in ("answer", "all") and args.judge_model in (env.get("qa_model"),):
        print("[WARN] judge model == answer model: self-preference bias. Use --judge-model with a different model if you can.")

    org_ids = args.org_id
    if args.all_orgs:
        data_root = EVAL_DIR / "data"
        org_ids = sorted(int(p.name.replace("org_", "")) for p in data_root.glob("org_*")
                         if p.is_dir() and p.name.replace("org_", "").isdigit() and any(p.glob("ground_truth*.jsonl")))
    if not org_ids:
        print("No tenants to evaluate.")
        return

    pipeline = build_safe_pipeline()
    summaries = []
    try:
        for oid in org_ids:
            s = await evaluate_tenant(pipeline, oid, args, env)
            if s:
                summaries.append(s)
    finally:
        try:
            await pipeline.vector_db.close()
        except Exception:  # noqa: BLE001
            pass

    if len(summaries) > 1:
        flat = [headline(s) for s in summaries]
        fields: List[str] = []
        for r in flat:
            for k in r:
                if k not in fields:
                    fields.append(k)
        path = EVAL_DIR / "data" / "multi_tenant_summary.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(flat)
        print(f"Saved multi-tenant rollup to {path.resolve()}")


def main() -> None:
    p = argparse.ArgumentParser(description="Read-only multi-tenant RAG evaluation.")
    p.add_argument("--org-id", type=int, nargs="+")
    p.add_argument("--all-orgs", action="store_true")
    p.add_argument("--filename", nargs="+", default=None, help="Dataset file(s) in data/org_<id>/ (default: ground_truth_v2.jsonl, else ground_truth.jsonl).")
    p.add_argument("--sets", nargs="+", default=None, help="standard colloquial negative human (default: all present).")
    p.add_argument("--stage", choices=["retrieval", "answer", "all"], default="all")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--max-samples", type=int, default=None, help="Cap per set.")
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p.add_argument("--skip-ragas", action="store_true")
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--parity-check", type=int, default=3, help="Queries to cross-check against QueryPipeline.execute() (0 = off). Costs a few LLM calls.")
    p.add_argument("--allow-prod-read", action="store_true", help="Required when settings point at the production Qdrant cluster.")
    p.add_argument("--sleep", type=float, default=0.1)
    args = p.parse_args()
    if not args.org_id and not args.all_orgs:
        p.error("Provide --org-id or --all-orgs.")
    asyncio.run(run_all(args))


if __name__ == "__main__":
    main()
