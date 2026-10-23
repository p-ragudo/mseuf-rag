"""Full evaluation runner (READ-ONLY against production) for the 3-part benchmark suite:
  1. 150 Synthetic QA Pairs (`ground_truth_150_blind.jsonl` or `ground_truth_150.jsonl`)
  2. 63 Official FAQ QA Pairs (`ground_truth_faqs_63_blind.jsonl` or `ground_truth_faqs_63.jsonl`)
  3. 71 Real-User Queries (`queries_real_users_71.jsonl` or `queries_real_users.jsonl` — evaluated on reference-free metrics)

Usage:
  uv run python -m evaluation.run_evaluation --org-id 1 \
    --filename ground_truth_150_blind.jsonl ground_truth_faqs_63_blind.jsonl queries_real_users_71.jsonl \
    --use-blind-queries --stage all --allow-prod-read
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import evaluation.compat  # noqa: E402,F401

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
    EVAL_DIR,
    content_sha,
    is_english_text,
    load_dataset_meta,
    normalize_record,
    read_jsonl,
    tenant_dir,
)
from evaluation.custom_judges import (  # noqa: E402
    run_abstention_judges,
    run_answer_judges,
    run_reference_free_judges,
)
from evaluation.generate_ground_truth import FAQ_URL, resolve_chunk_ids_for_texts  # noqa: E402
from evaluation.pipeline_inspector import execute_instrumented_query  # noqa: E402
from evaluation.reporting import headline, render_markdown, summarize  # noqa: E402
from evaluation.safety import (  # noqa: E402
    build_safe_pipeline,
    require_safe_environment,
    selftest_postgres_guard,
)
from evaluation.traditional_metrics import (  # noqa: E402
    compute_all_lexical_metrics,
    cosine_similarity,
    first_rank,
    first_url_rank,
    multi_gold_in_contexts,
    multi_gold_metrics,
)

DEFAULT_JUDGE_MODEL = "gemini-3.1-flash-lite"
SET_ALIASES = {
    "standard": "synthetic_150",
    "synthetic_100": "synthetic_150",
    "synthetic_150": "synthetic_150",
    "faqs": "faqs_63",
    "faqs_21": "faqs_63",
    "faqs_63": "faqs_63",
    "real_user": "real_user_71",
    "real_user_71": "real_user_71",
    "negative": "negative",
}


def resolve_filenames(org_id: int, requested: Optional[List[str]]) -> List[str]:
    if requested:
        return requested
    d = tenant_dir(org_id)
    default_suite = []
    for cand in (
        "ground_truth_150_blind.jsonl" if (d / "ground_truth_150_blind.jsonl").exists() else "ground_truth_150.jsonl",
        "ground_truth_faqs_63_blind.jsonl" if (d / "ground_truth_faqs_63_blind.jsonl").exists() else "ground_truth_faqs_63.jsonl",
        "queries_real_users_71.jsonl" if (d / "queries_real_users_71.jsonl").exists() else "queries_real_users.jsonl",
    ):
        if (d / cand).exists():
            default_suite.append(cand)
    return default_suite or ["ground_truth.jsonl"]


def load_records(
    org_id: int, filenames: List[str], sets: Optional[List[str]], use_blind: bool = False
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for fn in filenames:
        path = tenant_dir(org_id) / fn
        if not path.exists():
            raise FileNotFoundError(f"{path} not found.")
        meta = load_dataset_meta(path)
        if meta:
            if meta.get("active_collection") and meta["active_collection"] != settings.resolved_collection_name:
                print(
                    f"[WARN] {fn}: generated against collection {meta['active_collection']!r}, now {settings.resolved_collection_name!r}"
                )
            if meta.get("embedding_model") and meta["embedding_model"] != settings.embedding_model:
                print(
                    f"[WARN] {fn}: generated with embedding model {meta['embedding_model']!r}, now {settings.embedding_model!r}"
                )
        raw_list = read_jsonl(path)
        # Only cap if reading the raw un-expanded 27-item ground_truth_faqs.jsonl directly
        if fn == "ground_truth_faqs.jsonl" and len(raw_list) > 21:
            raw_list = raw_list[:21]
        for idx, raw in enumerate(raw_list, start=1):
            if "test_id" not in raw:
                raw = {
                    "test_id": f"org{org_id}_real_user_{idx}",
                    "set_name": "real_user_71",
                    "answerable": True,
                    "has_ground_truth": False,
                    "org_id": org_id,
                    "user_query": raw.get("user_query", ""),
                }
            records.append(normalize_record(raw, use_blind_query=use_blind))
    if sets:
        wanted = {SET_ALIASES.get(s, s) for s in sets}
        records = [r for r in records if r["set_name"] in wanted]
    return records


async def hydrate_and_drop_stale(org_id: int, records: List[Dict[str, Any]]):
    """Auto-resolves missing chunk IDs for FAQ items and prevents partial-snippet SHA mismatches."""
    for r in records:
        is_faq = "faq" in str(r.get("set_name", "")).lower()
        if r.get("has_ground_truth") and (not r.get("ground_truth_chunk_ids") or is_faq):
            cids, db_sha = await resolve_chunk_ids_for_texts(
                org_id,
                r.get("ground_truth_contexts") or [r.get("ground_truth_answer", "")],
                r.get("source_url") or (FAQ_URL if is_faq else None),
                query_hint=r.get("base_user_query") or r.get("user_query", ""),
            )
            if cids:
                r["ground_truth_chunk_ids"] = cids
                r["required_chunk_ids"] = cids[:1]
                r["primary_chunk_id"] = cids[0]
            if db_sha:
                r["ground_truth_content_sha"] = db_sha

    ids = sorted({
        int(cid)
        for r in records
        if r["answerable"] and r.get("has_ground_truth")
        for cid in (r.get("required_chunk_ids") or r.get("ground_truth_chunk_ids") or [])
        if cid is not None
    })
    current: Dict[int, str] = {}
    if ids:
        async with async_session() as session:
            rows = (await session.execute(select(Chunk.id, Chunk.content).where(Chunk.id.in_(ids)))).all()
        current = {int(i): content_sha(c) for i, c in rows}

    fresh, stale = [], []
    for r in records:
        if not r["answerable"] or not r.get("has_ground_truth"):
            fresh.append(r)
            continue
        is_faq = "faq" in str(r.get("set_name", "")).lower()
        pid = r.get("primary_chunk_id")
        sha = r.get("ground_truth_content_sha")

        # Never drop official FAQs as stale; align their SHA with the live DB chunk if present
        if is_faq:
            if pid is not None and int(pid) in current:
                r["ground_truth_content_sha"] = current[int(pid)]
            fresh.append(r)
            continue

        if pid is None and r.get("ground_truth_contexts"):
            fresh.append(r)
            continue
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


def build_row(rec: Dict[str, Any], res, k: int, answer_stage: bool) -> Dict[str, Any]:
    gold = rec.get("ground_truth_chunk_ids") or []
    req_gold = rec.get("required_chunk_ids") or gold
    answerable = bool(rec["answerable"])
    has_gt = bool(rec.get("has_ground_truth", True))
    texts = [c.content for c in res.expanded_contexts]
    urls = [c.source_url for c in res.expanded_contexts if c.source_url]

    def ids(cands):
        return [c.sql_chunk_id for c in cands]

    row: Dict[str, Any] = {
        "test_id": rec["test_id"],
        "set_name": rec["set_name"],
        "domain_cluster": rec.get("domain_cluster"),
        "difficulty": rec.get("difficulty"),
        "language": rec.get("language") or "English",
        "active_query_mode": rec.get("active_query_mode", "base"),
        "answerable": answerable,
        "has_ground_truth": has_gt,
        "negative_kind": rec.get("negative_kind"),
        "needs_review": rec.get("needs_review"),
        "cluster": rec["primary_chunk_id"] if (answerable and rec.get("primary_chunk_id") is not None) else rec["test_id"],
        "org_id": rec.get("org_id"),
        "campus": rec.get("campus"),
        "user_input": rec["user_query"],
        "base_user_query": rec.get("base_user_query"),
        "blind_user_query": rec.get("blind_user_query"),
        "reference": rec.get("ground_truth_answer"),
        "gt_url": rec.get("source_url"),
        "n_required_chunks": len(req_gold),
        "n_gold_equivalents": len(gold),
        "source": res.source,
        "fallback_reason": res.fallback_reason,
        "detected_campus": res.detected_campus,
        "response": res.answer,
        "retrieved_urls": urls,
        "answer_stage": answer_stage,
        "top_rerank_score": res.post_rerank_candidates[0].score if res.post_rerank_candidates else None,
        "latency_ms": res.latency_ms,
        "retrieval_latency_ms": res.retrieval_latency_ms,
        "_contexts": texts,
    }
    if answerable and has_gt:
        stage_lists = {
            "dense": res.dense_chunk_order,
            "sparse": res.sparse_chunk_order,
            "rrf": ids(res.pre_rerank_candidates),
            "rerank": ids(res.post_rerank_candidates),
            "final": ids(res.final_reranked_candidates),
        }
        for s_name, s_ids in stage_lists.items():
            row[f"rank_{s_name}"] = first_rank(s_ids, gold)
            if req_gold:
                mm = multi_gold_metrics(s_ids, req_gold, gold, k=k)
                row[f"precision_{s_name}"] = mm["precision"]
                row[f"recall_{s_name}"] = mm["recall"]
                row[f"all_hit_{s_name}"] = mm["all_hit"]
                row[f"ndcg_{s_name}"] = mm["ndcg"]
        row["url_rank_final_diagnostic"] = first_url_rank(
            [c.source_url for c in res.final_reranked_candidates], rec.get("source_url")
        )
        if rec.get("ground_truth_contexts"):
            any_hit, ctx_rec, ctx_rnk = multi_gold_in_contexts(rec["ground_truth_contexts"], texts)
            row["ctx_hit"] = any_hit
            row["ctx_recall"] = ctx_rec
            row["ctx_rank"] = ctx_rnk
            # If an FAQ item matched in expanded context or via FAQ URL, credit final stage if chunk ID was unmapped
            if row.get("rank_final") is None and any_hit and ctx_rnk is not None:
                row["rank_final"] = ctx_rnk
                row["recall_final"] = ctx_rec
                row["all_hit_final"] = 1.0 if ctx_rec == 1.0 else 0.0
                row["precision_final"] = round(1.0 / k, 4)
        else:
            row["ctx_hit"], row["ctx_recall"], row["ctx_rank"] = False, 0.0, None
    return row


async def compute_semantic_answer_similarities(pipeline, rows: List[Dict[str, Any]]) -> None:
    """Computes cosine similarity between embeddings of predicted answers and reference answers."""
    target_rows = [r for r in rows if r.get("response") and r.get("reference") and r.get("source") == "llm"]
    if not target_rows:
        return
    try:
        preds = [r["response"] for r in target_rows]
        refs = [r["reference"] for r in target_rows]
        pred_embs, ref_embs = await asyncio.gather(
            pipeline.embedder.embed(preds, task_type="RETRIEVAL_DOCUMENT"),
            pipeline.embedder.embed(refs, task_type="RETRIEVAL_DOCUMENT"),
        )
        for r, pe, re_ in zip(target_rows, pred_embs, ref_embs):
            r["answer_semantic_similarity"] = cosine_similarity(pe.values, re_.values)
    except Exception as e:  # noqa: BLE001
        print(f"[Semantic Answer Similarity Warning] {e!r}")


def setup_ragas_judge(judge_model_name: str, reference_free_only: bool = False):
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
    metrics = (
        [faithfulness, answer_relevancy]
        if reference_free_only
        else [context_precision, context_recall, faithfulness, answer_relevancy, answer_correctness]
    )
    for m in metrics:
        m.llm = wrapped_llm
        if hasattr(m, "embeddings"):
            m.embeddings = wrapped_emb
    return metrics


def run_ragas(rows: List[Dict[str, Any]], judge_model: str, reference_free_only: bool = False) -> None:
    import concurrent.futures
    import pandas as pd
    from datasets import Dataset

    df = pd.DataFrame([
        {
            "user_input": r["user_input"],
            "retrieved_contexts": r["_contexts"] or ["No context retrieved."],
            "response": r["response"],
            "reference": r.get("reference") or "",
        }
        for r in rows
    ])
    dataset = Dataset.from_pandas(df)

    def _isolated_worker():
        import asyncio
        from ragas import evaluate

        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            metrics = setup_ragas_judge(judge_model, reference_free_only=reference_free_only)
            result = evaluate(dataset=dataset, metrics=metrics)
            return result.to_pandas()
        finally:
            new_loop.close()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_isolated_worker)
            scores = future.result(timeout=600)
    except Exception as exc:
        print(f"[Ragas Isolated Worker Warning] {exc!r}. Skipping Ragas metrics for this set.")
        return

    cols = (
        ("faithfulness", "answer_relevancy")
        if reference_free_only
        else ("context_precision", "context_recall", "faithfulness", "answer_relevancy", "answer_correctness")
    )
    for i, r in enumerate(rows):
        for col in cols:
            if col in scores.columns:
                v = scores[col].iloc[i]
                r[col] = None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)


async def run_answer_stage(pipeline, rows: List[Dict[str, Any]], judge_model: str, skip_ragas: bool) -> Dict[str, Any]:
    answerable = [
        r for r in rows if r["answerable"] and r.get("has_ground_truth", True) and r["source"] == "llm" and r.get("reference")
    ]
    real_user_answered = [
        r for r in rows if r["answerable"] and not r.get("has_ground_truth", True) and r["source"] == "llm"
    ]
    neg = [r for r in rows if not r["answerable"]]
    info = {
        "judge_failures": 0,
        "real_user_judge_failures": 0,
        "abstention_judge_failures": 0,
        "ragas_error": None,
    }

    # Traditional lexical metrics (BLEU, ROUGE, Token F1): ONLY run when query/answer & reference are in English
    for r in answerable:
        is_eng_row = (r.get("language") == "English") and is_english_text(r["response"])
        if is_eng_row:
            r.update(compute_all_lexical_metrics(prediction=r["response"], reference=r["reference"], require_english_match=True))
        else:
            r.update({
                "token_precision": None,
                "token_recall": None,
                "token_f1": None,
                "bleu": None,
                "rouge_1": None,
                "rouge_2": None,
                "rouge_l": None,
            })

    await compute_semantic_answer_similarities(pipeline, answerable)

    if answerable:
        print(f"[Answer stage] custom judges on {len(answerable)} ground-truth rows ({judge_model}) ...")
        inputs = [
            {
                "test_id": r["test_id"],
                "user_input": r["user_input"],
                "reference": r["reference"],
                "retrieved_contexts": r["_contexts"] or ["No context retrieved."],
                "response": r["response"],
            }
            for r in answerable
        ]
        scores, failed = await run_answer_judges(inputs, judge_model)
        info["judge_failures"] = failed
        for r in answerable:
            r.update(scores.get(r["test_id"], {}))

    if real_user_answered:
        print(f"[Answer stage] reference-free triad judge on {len(real_user_answered)} real-user rows ({judge_model}) ...")
        ru_inputs = [
            {
                "test_id": r["test_id"],
                "user_input": r["user_input"],
                "retrieved_contexts": r["_contexts"] or ["No context retrieved."],
                "response": r["response"],
            }
            for r in real_user_answered
        ]
        ru_scores, ru_failed = await run_reference_free_judges(ru_inputs, judge_model)
        info["real_user_judge_failures"] = ru_failed
        for r in real_user_answered:
            r.update(ru_scores.get(r["test_id"], {}))

    for r in neg:
        if r["source"] == "fallback":
            r["abstained"], r["asserted_unsupported_facts"] = True, False
    to_judge = [
        {
            "test_id": r["test_id"],
            "user_input": r["user_input"],
            "retrieved_contexts": r["_contexts"] or ["No context retrieved."],
            "response": r["response"],
        }
        for r in neg
        if r["source"] == "llm"
    ]
    if to_judge:
        print(f"[Answer stage] abstention judge on {len(to_judge)} negative rows ...")
        verdicts, f2 = await run_abstention_judges(to_judge, judge_model)
        info["abstention_judge_failures"] = f2
        for r in neg:
            if r["test_id"] in verdicts:
                r.update(verdicts[r["test_id"]])

    if skip_ragas:
        return info

    if answerable:
        print(f"[Answer stage] Ragas on {len(answerable)} ground-truth rows ...")
        try:
            run_ragas(answerable, judge_model, reference_free_only=False)
        except Exception as e:  # noqa: BLE001
            info["ragas_error"] = repr(e)
            print(f"[Ragas ERROR on GT rows] {e!r}")

    if real_user_answered:
        print(f"[Answer stage] Reference-Free Ragas (faithfulness + answer_relevancy) on {len(real_user_answered)} real-user rows ...")
        try:
            run_ragas(real_user_answered, judge_model, reference_free_only=True)
        except Exception as e:  # noqa: BLE001
            print(f"[Ragas ERROR on real-user rows] {e!r}")

    return info


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
            print(
                f"  [Parity MISMATCH] {r['test_id']}: production={len(prod.contexts)} contexts, inspector={len(mine.expanded_contexts)}"
            )
    msg = f"{same}/{len(sample)} identical"
    print(f"[Parity] {msg}")
    if sample and same == 0:
        raise SystemExit("Parity check failed for every sampled query: fix pipeline_inspector.py.")
    return msg


def write_outputs(run_dir: Path, rows: List[Dict[str, Any]], summary: Dict[str, Any], md: str, config: Dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "rows.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    flat = [
        {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in r.items() if k != "_contexts"}
        for r in rows
    ]
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


async def evaluate_tenant(pipeline, org_id: int, args, env: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    answer_stage = args.stage in ("answer", "all")
    filenames = resolve_filenames(org_id, args.filename)
    records = load_records(org_id, filenames, args.sets, use_blind=args.use_blind_queries)
    records, stale = await hydrate_and_drop_stale(org_id, records)
    records = cap_per_set(records, args.max_samples)
    if not records:
        print(f"[Skip] no usable records for org_{org_id}.")
        return None
    org_name = records[0].get("org_name", f"Org {org_id}")

    counts: Dict[str, int] = {}
    for r in records:
        counts[r["set_name"]] = counts.get(r["set_name"], 0) + 1
    print("\n" + "=" * 78)
    print(
        f"EVALUATING {org_name} (org_id={org_id}) | top_k={args.top_k} | stage={args.stage} | sets={counts} | stale skipped={len(stale)}"
    )
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
                res = await execute_instrumented_query(
                    pipeline, org_id, rec["user_query"], args.top_k, generate_answer=answer_stage
                )
                break
            except Exception as e:  # noqa: BLE001
                print(f"  [retry {attempt + 1}/3] {rec['test_id']}: {e!r}")
                await asyncio.sleep(3 * (attempt + 1))
        if res is None:
            errors += 1
            continue
        row = build_row(rec, res, args.top_k, answer_stage)
        rows.append(row)
        print(
            f"  [{idx}/{len(records)}] {rec['set_name'][:12]:<12} {row['language'][:7]:<7} {rec.get('difficulty', 'n/a')[:6]:<6} "
            f"rrf={row.get('rank_rrf')} final={row.get('rank_final')} rec@k={row.get('recall_final')} "
            f"ctx={row.get('ctx_hit')} src={row['source']} {row['latency_ms']:.0f}ms"
        )
        await asyncio.sleep(args.sleep)
    if errors:
        print(f"[WARN] {errors} queries failed after retries and were excluded.")

    answer_info: Dict[str, Any] = {}
    if answer_stage:
        answer_info = await run_answer_stage(pipeline, rows, args.judge_model, args.skip_ragas)

    query_mode = "blind" if (args.use_blind_queries or any(r.get("active_query_mode") == "blind" for r in rows)) else "base"
    meta = {
        "org_id": org_id,
        "org_name": org_name,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "top_k": args.top_k,
        "query_mode": query_mode,
        "n_boot": args.bootstrap,
        "stage": args.stage,
        "dataset_files": filenames,
        "stale_skipped": len(stale),
        "excluded_errors": errors,
        "parity": parity,
        "qdrant_collection": env.get("qdrant_collection"),
        "qa_model": env.get("qa_model"),
        "judge_model": args.judge_model if answer_stage else None,
        "embedding_model": env.get("embedding_model"),
        "answer_stage_info": answer_info,
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
    print("[Safety] Postgres write guard self-test passed.")
    if args.stage in ("answer", "all") and args.judge_model in (env.get("qa_model"),):
        print("[WARN] judge model == answer model: self-preference bias.")

    org_ids = args.org_id
    if args.all_orgs:
        data_root = EVAL_DIR / "data"
        org_ids = sorted(
            int(p.name.replace("org_", ""))
            for p in data_root.glob("org_*")
            if p.is_dir() and p.name.replace("org_", "").isdigit() and any(p.glob("*.jsonl"))
        )
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
    p = argparse.ArgumentParser(description="Read-only multi-tenant RAG evaluation (150 Synthetic + 63 FAQs + 71 Real Users = 284 queries).")
    p.add_argument("--org-id", type=int, nargs="+")
    p.add_argument("--all-orgs", action="store_true")
    p.add_argument("--filename", nargs="+", default=None, help="Dataset file(s) in data/org_<id>/.")
    p.add_argument("--sets", nargs="+", default=None)
    p.add_argument("--use-blind-queries", action="store_true", help="Force evaluation to use blind_user_query when present.")
    p.add_argument("--stage", choices=["retrieval", "answer", "all"], default="all")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--max-samples", type=int, default=None)
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p.add_argument("--skip-ragas", action="store_true")
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--parity-check", type=int, default=3)
    p.add_argument("--allow-prod-read", action="store_true")
    p.add_argument("--sleep", type=float, default=0.1)
    args = p.parse_args()
    if not args.org_id and not args.all_orgs:
        p.error("Provide --org-id or --all-orgs.")
    asyncio.run(run_all(args))


if __name__ == "__main__":
    main()