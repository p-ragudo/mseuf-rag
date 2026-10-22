import sys
import types
import asyncio

# ==============================================================================
# 🚨 PYTHON 3.14 + GREENLET + HTTPCORE + RAGAS COMPATIBILITY SHIMS 🚨
# ==============================================================================

dummy_nest = types.ModuleType("nest_asyncio")
dummy_nest.apply = lambda *args, **kwargs: None
sys.modules["nest_asyncio"] = dummy_nest

import asyncio.timeouts as _asyncio_timeouts


class _GreenletSafeTimeout:
    def __init__(self, when: float | None) -> None:
        self._when = when
        self._expired = False

    def when(self) -> float | None:
        return self._when

    def reschedule(self, when: float | None) -> None:
        self._when = when

    def expired(self) -> bool:
        return self._expired

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


def _safe_timeout(delay: float | None) -> _GreenletSafeTimeout:
    try:
        loop = asyncio._get_running_loop()
        when = (loop.time() + delay) if (delay is not None and loop is not None) else None
    except Exception:
        when = None
    return _GreenletSafeTimeout(when)


def _safe_timeout_at(when: float | None) -> _GreenletSafeTimeout:
    return _GreenletSafeTimeout(when)


_asyncio_timeouts.Timeout = _GreenletSafeTimeout  # type: ignore
_asyncio_timeouts.timeout = _safe_timeout  # type: ignore
_asyncio_timeouts.timeout_at = _safe_timeout_at  # type: ignore
asyncio.Timeout = _GreenletSafeTimeout  # type: ignore
asyncio.timeout = _safe_timeout  # type: ignore
asyncio.timeout_at = _safe_timeout_at  # type: ignore

try:
    import aiohttp.helpers as _aiohttp_helpers
    import aiohttp.connector as _aiohttp_connector

    def _safe_ceil_timeout(delay: float | None, ceil_threshold: float = 5) -> _GreenletSafeTimeout:
        return _safe_timeout(delay)

    _aiohttp_helpers.ceil_timeout = _safe_ceil_timeout  # type: ignore
    _aiohttp_connector.ceil_timeout = _safe_ceil_timeout  # type: ignore
except ImportError:
    pass

try:
    import sniffio
    sniffio.current_async_library = lambda: "asyncio"
except ImportError:
    pass

try:
    import httpcore._synchronization as _hc_sync
    _hc_sync.current_async_library = lambda: "asyncio"
except ImportError:
    pass

try:
    import langchain_community.chat_models.vertexai  # type: ignore
except ImportError:
    dummy_vertex = types.ModuleType("langchain_community.chat_models.vertexai")
    dummy_vertex.ChatVertexAI = type("ChatVertexAI", (object,), {})
    sys.modules["langchain_community.chat_models.vertexai"] = dummy_vertex

# ==============================================================================
# END SHIMS
# ==============================================================================

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from datasets import Dataset
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    answer_correctness,
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.services.query_pipeline.query_pipeline import QueryPipeline
from app.services.semantic_cache.base import BaseSemanticCache
from app.services.semantic_cache.schemas import CacheEntry, CacheMetadata
from evaluation.custom_judges import run_custom_judges_batch
from evaluation.pipeline_inspector import execute_instrumented_query
from evaluation.traditional_metrics import (
    compute_all_lexical_metrics,
    compute_ranking_metrics,
)


class NoOpSemanticCache(BaseSemanticCache):
    """Bypasses semantic cache during evaluation so every query tests live Qdrant + LLM."""

    async def get(self, vector: List[float], org_id: int | str) -> Optional[CacheEntry]:
        return None

    async def set(
        self,
        query: str,
        vector: List[float],
        response: str,
        org_id: int | str,
        metadata: Optional[CacheMetadata] = None,
    ) -> None:
        return None

    async def clear(self) -> None:
        return None


def load_tenant_dataset(org_id: int, filename: str = "ground_truth.jsonl") -> List[Dict[str, Any]]:
    dataset_path = CURRENT_DIR / "data" / f"org_{org_id}" / filename
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Ground truth dataset not found for org_{org_id} at {dataset_path}. "
            f"Run `uv run python -m evaluation.generate_ground_truth --org-id {org_id}` first."
        )

    records = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def check_chunk_in_expanded_contexts(
    gt_chunk_text: str, retrieved_contexts: List[str]
) -> tuple[bool, Optional[int]]:
    lines = gt_chunk_text.strip().splitlines()
    body = "\n".join(lines[1:]).strip() if lines and lines[0].startswith("Section:") else gt_chunk_text.strip()
    mid = max(0, len(body) // 4)
    anchor = " ".join(body[mid : mid + 150].split())

    for idx, ctx in enumerate(retrieved_contexts, start=1):
        norm_ctx = " ".join(ctx.split())
        if anchor and anchor in norm_ctx:
            return True, idx
    return False, None


def setup_ragas_judge(judge_model_name: str = "gemini-3.8-flash"):
    api_key = settings.llm_qa_api_key or settings.llm_qgen_api_key
    os.environ["GOOGLE_API_KEY"] = api_key

    judge_llm = ChatGoogleGenerativeAI(
        model=judge_model_name,
        temperature=0.0,
        google_api_key=api_key,
    )

    emb_model = getattr(settings, "embedding_model", None) or "gemini-embedding-2"
    if not emb_model.startswith("models/"):
        emb_model = f"models/{emb_model}"

    judge_emb = GoogleGenerativeAIEmbeddings(
        model=emb_model,
        google_api_key=api_key,
    )

    wrapped_llm = LangchainLLMWrapper(judge_llm)
    wrapped_emb = LangchainEmbeddingsWrapper(judge_emb)

    metrics = [context_precision, context_recall, faithfulness, answer_relevancy, answer_correctness]
    for m in metrics:
        m.llm = wrapped_llm
        if hasattr(m, "embeddings"):
            m.embeddings = wrapped_emb

    return metrics


async def run_pipeline_and_judges_async(
    org_id: int,
    records: List[Dict[str, Any]],
    top_k: int,
    disable_cache: bool,
    judge_model: str,
) -> List[Dict[str, Any]]:
    """Runs Phase 1 (Pipeline) and Phase 2 (Custom Judges) in a single isolated event loop."""
    pipeline = QueryPipeline()
    if disable_cache:
        pipeline.semantic_cache = NoOpSemanticCache()

    async def _mock_resolve_org_details(oid):
        return records[0].get("org_name", f"Org {oid}"), [], int(records[0].get("content_version", 0))

    pipeline._resolve_org_details = _mock_resolve_org_details  # type: ignore

    eval_rows: List[Dict[str, Any]] = []

    try:
        print("[Stage 1/3] Executing Instrumented Query Pipeline (Hybrid Search + RRF + Reranker)...")
        for idx, item in enumerate(records, start=1):
            query_text = item["user_query"]
            gt_answer = item["ground_truth_answer"]
            gt_contexts = item["ground_truth_contexts"]
            gt_chunk_ids = [int(x) for x in item.get("ground_truth_chunk_ids", [])]
            gt_url = item["source_url"]

            t0 = time.perf_counter()
            res = await execute_instrumented_query(pipeline, org_id, query_text, top_k)
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)

            pre_chunk_ids = [c.sql_chunk_id or -1 for c in res.pre_rerank_candidates]
            pre_urls = [c.source_url for c in res.pre_rerank_candidates]
            pre_ir = compute_ranking_metrics(
                ranked_chunk_ids=pre_chunk_ids,
                ranked_urls=pre_urls,
                gt_chunk_ids=gt_chunk_ids,
                gt_url=gt_url,
                k=top_k,
            )

            post_chunk_ids = [c.sql_chunk_id or -1 for c in res.final_reranked_candidates]
            post_urls = [c.source_url for c in res.final_reranked_candidates]
            post_ir = compute_ranking_metrics(
                ranked_chunk_ids=post_chunk_ids,
                ranked_urls=post_urls,
                gt_chunk_ids=gt_chunk_ids,
                gt_url=gt_url,
                k=top_k,
            )

            pre_r = pre_ir["effective_rank"]
            post_r = post_ir["effective_rank"]
            rank_delta = (pre_r - post_r) if (pre_r is not None and post_r is not None) else 0

            retrieved_texts = [c.content for c in res.expanded_contexts]
            retrieved_urls = [c.source_url for c in res.expanded_contexts if c.source_url]
            isolation_passed = True

            chunk_hit, hit_rank = check_chunk_in_expanded_contexts(gt_contexts[0], retrieved_texts)
            url_hit = gt_url in retrieved_urls
            reciprocal_rank = (1.0 / hit_rank) if hit_rank else 0.0

            lexical = compute_all_lexical_metrics(prediction=res.answer, reference=gt_answer)

            print(
                f"  [{idx}/{len(records)}] Query: '{query_text[:40]}...' | "
                f"PreRank={pre_r} -> PostRank={post_r} (Δ={rank_delta:+d}) | "
                f"Hit@{top_k}={int(post_ir['hit_at_k'])} | F1={lexical['token_f1']:.2f} | {latency_ms}ms"
            )

            eval_rows.append(
                {
                    "test_id": item["test_id"],
                    "org_id": org_id,
                    "campus": item.get("campus", "main"),
                    "user_input": query_text,
                    "retrieved_contexts": retrieved_texts if retrieved_texts else ["No context retrieved."],
                    "response": res.answer,
                    "reference": gt_answer,
                    "reference_contexts": gt_contexts,
                    "gt_url": gt_url,
                    "retrieved_urls": retrieved_urls,
                    "pre_rerank_rank": pre_r,
                    "pre_rerank_hit_at_k": pre_ir["hit_at_k"],
                    "pre_rerank_rr": pre_ir["rr"],
                    "pre_rerank_ndcg_at_k": pre_ir["ndcg_at_k"],
                    "post_rerank_rank": post_r,
                    "post_rerank_hit_at_k": post_ir["hit_at_k"],
                    "post_rerank_rr": post_ir["rr"],
                    "post_rerank_ndcg_at_k": post_ir["ndcg_at_k"],
                    "reranker_rank_delta": rank_delta,
                    "chunk_hit": chunk_hit,
                    "url_hit": url_hit,
                    "reciprocal_rank": reciprocal_rank,
                    "bleu": lexical["bleu"],
                    "rouge_1": lexical["rouge_1"],
                    "rouge_2": lexical["rouge_2"],
                    "rouge_l": lexical["rouge_l"],
                    "token_precision": lexical["token_precision"],
                    "token_recall": lexical["token_recall"],
                    "token_f1": lexical["token_f1"],
                    "tenant_isolation_passed": isolation_passed,
                    "pipeline_source": res.source,
                    "latency_ms": latency_ms,
                }
            )
            await asyncio.sleep(0.1)

    finally:
        try:
            await pipeline.vector_db.close()
        except Exception:
            pass

    print(f"\n[Stage 2/3] Running Batched Custom Rubric Judges ({judge_model})...")
    custom_scores_map = await run_custom_judges_batch(eval_rows, judge_model=judge_model)
    for row in eval_rows:
        c_score = custom_scores_map.get(row["test_id"], {})
        row["groundedness"] = c_score.get("groundedness")
        row["completeness"] = c_score.get("completeness")
        row["helpfulness"] = c_score.get("helpfulness")
        row["source_sufficiency"] = c_score.get("source_sufficiency")
        row["judge_rationale"] = c_score.get("judge_rationale", "")

    return eval_rows


def process_tenant(
    org_id: int,
    top_k: int,
    max_samples: Optional[int],
    disable_cache: bool,
    judge_model: str,
    filename: str,
    ragas_metrics: list,
) -> Optional[Dict[str, Any]]:
    tenant_dir = CURRENT_DIR / "data" / f"org_{org_id}"
    records = load_tenant_dataset(org_id=org_id, filename=filename)
    if max_samples and max_samples > 0:
        records = records[:max_samples]

    if not records:
        print(f"[Skip] Empty ground truth file for org_{org_id}.")
        return None

    org_name = records[0].get("org_name", f"Org {org_id}")

    print(f"\n" + "=" * 78)
    print(f"EVALUATING TENANT: {org_name} (org_id={org_id}) | Test Cases: {len(records)} | Top-K: {top_k}")
    print("=" * 78)

    # Run Phases 1 and 2 in an isolated event loop using asyncio.run()
    eval_rows = asyncio.run(
        run_pipeline_and_judges_async(
            org_id=org_id,
            records=records,
            top_k=top_k,
            disable_cache=disable_cache,
            judge_model=judge_model,
        )
    )

    # Run Phase 3: Ragas Evaluation (Synchronous in main thread to avoid loop conflicts)
    print(f"\n[Stage 3/3] Running Ragas Evaluation Suite ({judge_model})...")
    ragas_input_df = pd.DataFrame(
        [
            {
                "user_input": r["user_input"],
                "retrieved_contexts": r["retrieved_contexts"],
                "response": r["response"],
                "reference": r["reference"],
            }
            for r in eval_rows
        ]
    )

    hf_dataset = Dataset.from_pandas(ragas_input_df)
    ragas_result = evaluate(dataset=hf_dataset, metrics=ragas_metrics)
    scores_df = ragas_result.to_pandas()

    meta_df = pd.DataFrame(eval_rows)
    for col in ["context_precision", "context_recall", "faithfulness", "answer_relevancy", "answer_correctness"]:
        if col in scores_df.columns:
            meta_df[col] = scores_df[col]

    report_csv_path = tenant_dir / "evaluation_report.csv"
    meta_df.to_csv(report_csv_path, index=False)

    def _mean(col_name: str) -> Optional[float]:
        if col_name in meta_df.columns and meta_df[col_name].notna().any():
            return round(float(meta_df[col_name].dropna().mean()), 4)
        return None

    summary = {
        "org_id": org_id,
        "org_name": org_name,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "num_samples": len(eval_rows),
        "top_k": top_k,
        "context_precision": _mean("context_precision"),
        "context_recall": _mean("context_recall"),
        "pre_rerank_hit_at_k": _mean("pre_rerank_hit_at_k"),
        "post_rerank_hit_at_k": _mean("post_rerank_hit_at_k"),
        "reranker_hit_lift": round(
            (_mean("post_rerank_hit_at_k") or 0.0) - (_mean("pre_rerank_hit_at_k") or 0.0), 4
        ),
        "pre_rerank_mrr": _mean("pre_rerank_rr"),
        "post_rerank_mrr": _mean("post_rerank_rr"),
        "reranker_mrr_lift": round(
            (_mean("post_rerank_rr") or 0.0) - (_mean("pre_rerank_rr") or 0.0), 4
        ),
        "pre_rerank_ndcg_at_k": _mean("pre_rerank_ndcg_at_k"),
        "post_rerank_ndcg_at_k": _mean("post_rerank_ndcg_at_k"),
        "reranker_ndcg_lift": round(
            (_mean("post_rerank_ndcg_at_k") or 0.0) - (_mean("pre_rerank_ndcg_at_k") or 0.0), 4
        ),
        "avg_reranker_rank_delta": _mean("reranker_rank_delta"),
        "faithfulness": _mean("faithfulness"),
        "groundedness": _mean("groundedness"),
        "answer_relevancy": _mean("answer_relevancy"),
        "answer_correctness": _mean("answer_correctness"),
        "completeness": _mean("completeness"),
        "helpfulness": _mean("helpfulness"),
        "source_sufficiency": _mean("source_sufficiency"),
        "token_f1": _mean("token_f1"),
        "token_precision": _mean("token_precision"),
        "token_recall": _mean("token_recall"),
        "bleu": _mean("bleu"),
        "rouge_1": _mean("rouge_1"),
        "rouge_2": _mean("rouge_2"),
        "rouge_l": _mean("rouge_l"),
        "tenant_isolation_pass_rate": _mean("tenant_isolation_passed"),
        "avg_latency_ms": _mean("latency_ms"),
    }

    summary_json_path = tenant_dir / "summary_metrics.json"
    with open(summary_json_path, "w", encoding="utf-8") as sf:
        json.dump(summary, sf, indent=2)

    print("\n" + "=" * 78)
    print(f"TENANT EVALUATION SUMMARY: {org_name} (org_id={org_id})")
    print("=" * 78)
    for k, v in summary.items():
        print(f"  {k:<30}: {v}")
    print("=" * 78)
    print(f"Saved sample-level CSV : {report_csv_path.resolve()}")
    print(f"Saved aggregate JSON   : {summary_json_path.resolve()}")

    return summary


def discover_generated_tenant_dirs(filename: str = "ground_truth.jsonl") -> List[int]:
    data_root = CURRENT_DIR / "data"
    if not data_root.exists():
        return []
    org_ids = []
    for sub in sorted(data_root.iterdir()):
        if sub.is_dir() and sub.name.startswith("org_"):
            try:
                oid = int(sub.name.replace("org_", ""))
                if (sub / filename).exists():
                    org_ids.append(oid)
            except ValueError:
                continue
    return org_ids


def main():
    parser = argparse.ArgumentParser(
        description="Full Multi-Tenant RAG Evaluation Suite (Ragas + Reranker Lift + Custom Rubrics + Lexical)."
    )
    parser.add_argument(
        "--org-id",
        type=int,
        nargs="+",
        help="Specific organization ID(s) to evaluate (e.g., --org-id 1 2).",
    )
    parser.add_argument(
        "--all-orgs",
        action="store_true",
        help="Evaluate all tenant folders under backend/evaluation/data/org_<id>/.",
    )
    parser.add_argument(
        "--filename",
        type=str,
        default="ground_truth.jsonl",
        help="Ground truth JSONL filename inside each tenant folder.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Top-K retrieval setting (default: 5).",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Optional cap on number of samples to evaluate per tenant.",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default="gemini-3.8-flash",
        help="Gemini model used for Ragas and Custom Rubric Judges (default: gemini-3.8-flash).",
    )
    parser.add_argument(
        "--disable-cache",
        action="store_true",
        default=True,
        help="Bypass semantic cache so live retrieval and generation are tested (default: True).",
    )
    args = parser.parse_args()

    if not args.org_id and not args.all_orgs:
        parser.error("Provide either --org-id <id...> or --all-orgs.")

    target_org_ids = (
        discover_generated_tenant_dirs(args.filename)
        if args.all_orgs
        else args.org_id
    )

    if not target_org_ids:
        print("No tenant ground-truth datasets found to evaluate.")
        return

    print("[Init] Starting evaluation runner...")
    ragas_metrics = setup_ragas_judge(judge_model_name=args.judge_model)
    all_summaries = []

    for oid in target_org_ids:
        summary = process_tenant(
            org_id=oid,
            top_k=args.top_k,
            max_samples=args.max_samples,
            disable_cache=args.disable_cache,
            judge_model=args.judge_model,
            filename=args.filename,
            ragas_metrics=ragas_metrics,
        )
        if summary:
            all_summaries.append(summary)

    if len(all_summaries) > 1:
        rollup_df = pd.DataFrame(all_summaries)
        rollup_path = CURRENT_DIR / "data" / "multi_tenant_summary.csv"
        rollup_df.to_csv(rollup_path, index=False)
        print("\n" + "=" * 78)
        print("GLOBAL MULTI-TENANT ROLLUP")
        print("=" * 78)
        print(rollup_df.to_string(index=False))
        print(f"\nSaved multi-tenant comparison table to: {rollup_path.resolve()}")


if __name__ == "__main__":
    main()