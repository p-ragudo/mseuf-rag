"""Turns per-query rows into summary statistics (with confidence intervals, dataset-level rollups, and language breakdowns)."""
import math
from typing import Any, Dict, List, Optional

from evaluation.stats import (
    auc_pos_vs_neg,
    best_threshold,
    cluster_bootstrap_mean,
    mcnemar_exact,
    percentile,
    spearman,
)
from evaluation.traditional_metrics import rank_metrics

STAGES = [
    ("dense", "rank_dense"),
    ("sparse", "rank_sparse"),
    ("rrf", "rank_rrf"),
    ("rerank", "rank_rerank"),
    ("final", "rank_final"),
]
STAGE_LABELS = {
    "dense": "Dense only (question vectors)",
    "sparse": "Sparse only (BM25 on chunk text)",
    "rrf": "Hybrid RRF (before reranker)",
    "rerank": "After cross-encoder (reranker only)",
    "final": "Final (threshold + temporal + top-k)",
}
ANSWER_METRICS = [
    "groundedness",
    "completeness",
    "helpfulness",
    "context_sufficiency",
    "answer_semantic_similarity",
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "answer_correctness",
    "token_precision",
    "token_recall",
    "token_f1",
    "bleu",
    "rouge_1",
    "rouge_2",
    "rouge_l",
]
AGREEMENT_PAIRS = [
    ("faithfulness", "groundedness"),
    ("answer_correctness", "completeness"),
    ("context_recall", "context_sufficiency"),
    ("answer_relevancy", "helpfulness"),
    ("answer_semantic_similarity", "completeness"),
]


def _isnum(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and not (isinstance(x, float) and math.isnan(x))


def _block(values: List[float], clusters: List[Any], n_boot: int, seed: int) -> Dict[str, Any]:
    return cluster_bootstrap_mean(values, clusters, n_boot=n_boot, seed=seed)


def retrieval_block(pos: List[Dict[str, Any]], k: int, n_boot: int, seed: int) -> Dict[str, Dict[str, Any]]:
    cl = [r["cluster"] for r in pos]
    out: Dict[str, Dict[str, Any]] = {}
    for name, key in STAGES:
        ranks = [r.get(key) for r in pos]
        ms = [rank_metrics(x, k) for x in ranks]
        precisions = [r.get(f"precision_{name}", (1.0 / k if m["hit"] else 0.0)) for r, m in zip(pos, ms)]
        recalls = [r.get(f"recall_{name}", m["hit"]) for r, m in zip(pos, ms)]
        all_hits = [r.get(f"all_hit_{name}", m["hit"]) for r, m in zip(pos, ms)]
        ndcgs = [r.get(f"ndcg_{name}", m["ndcg"]) for r, m in zip(pos, ms)]
        out[name] = {
            "hit@1": _block([1.0 if (x is not None and x <= 1) else 0.0 for x in ranks], cl, n_boot, seed),
            "hit@k": _block([m["hit"] for m in ms], cl, n_boot, seed),
            "precision@k": _block(precisions, cl, n_boot, seed),
            "recall@k": _block(recalls, cl, n_boot, seed),
            "all_hit@k": _block(all_hits, cl, n_boot, seed),
            "mrr@k": _block([m["rr"] for m in ms], cl, n_boot, seed),
            "ndcg@k": _block(ndcgs, cl, n_boot, seed),
            "in_pool": _block([1.0 if x is not None else 0.0 for x in ranks], cl, n_boot, seed),
        }
    return out


def slice_breakdown(pos: List[Dict[str, Any]], slice_key: str, k: int, n_boot: int, seed: int) -> Dict[str, Dict[str, Any]]:
    """Computes retrieval and answer metrics grouped by a metadata key (e.g. 'language', 'difficulty', 'domain_cluster')."""
    out: Dict[str, Dict[str, Any]] = {}
    keys = sorted({str(r.get(slice_key) or "English") for r in pos})
    for val in keys:
        sub = [r for r in pos if str(r.get(slice_key) or "English") == val]
        if not sub:
            continue
        cl = [r["cluster"] for r in sub]
        ranks = [r.get("rank_final") for r in sub]
        ms = [rank_metrics(x, k) for x in ranks]
        recalls = [r.get("recall_final", m["hit"]) for r, m in zip(sub, ms)]
        all_hits = [r.get("all_hit_final", m["hit"]) for r, m in zip(sub, ms)]
        ctx_vals = [
            float(r["ctx_recall"]) if _isnum(r.get("ctx_recall")) else (1.0 if r.get("ctx_hit") else 0.0)
            for r in sub
        ]
        entry: Dict[str, Any] = {
            "n": len(sub),
            "hit@k": _block([m["hit"] for m in ms], cl, n_boot, seed),
            "recall@k": _block(recalls, cl, n_boot, seed),
            "all_hit@k": _block(all_hits, cl, n_boot, seed),
            "mrr@k": _block([m["rr"] for m in ms], cl, n_boot, seed),
            "ctx_recall": _block(ctx_vals, cl, n_boot, seed),
        }
        for m_name in ("groundedness", "completeness", "answer_semantic_similarity", "token_f1", "rouge_l", "bleu"):
            vs = [(r[m_name], r["cluster"]) for r in sub if _isnum(r.get(m_name))]
            if vs:
                entry[m_name] = _block([v for v, _ in vs], [c for _, c in vs], n_boot, seed)
        out[val] = entry
    return out


def paired_effect(pos: List[Dict[str, Any]], a_key: str, b_key: str, k: int, n_boot: int, seed: int) -> Dict[str, Any]:
    cl = [r["cluster"] for r in pos]
    a_rank = [r.get(a_key) for r in pos]
    b_rank = [r.get(b_key) for r in pos]
    a_hit = [1 if (x is not None and x <= k) else 0 for x in a_rank]
    b_hit = [1 if (x is not None and x <= k) else 0 for x in b_rank]
    rescued = sum(1 for a, b in zip(a_hit, b_hit) if b and not a)
    harmed = sum(1 for a, b in zip(a_hit, b_hit) if a and not b)
    return {
        "n": len(pos),
        "rescued": rescued,
        "harmed": harmed,
        "both_hit": sum(1 for a, b in zip(a_hit, b_hit) if a and b),
        "both_miss": sum(1 for a, b in zip(a_hit, b_hit) if not a and not b),
        "delta_hit@k": _block([b - a for a, b in zip(a_hit, b_hit)], cl, n_boot, seed),
        "delta_mrr@k": _block([rank_metrics(b, k)["rr"] - rank_metrics(a, k)["rr"] for a, b in zip(a_rank, b_rank)], cl, n_boot, seed),
        "mcnemar_p": mcnemar_exact(rescued, harmed),
    }


def summarize(
    rows: List[Dict[str, Any]],
    k: int,
    n_boot: int = 1000,
    seed: int = 0,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta = meta or {}
    out: Dict[str, Any] = {
        "meta": meta,
        "n": {},
        "retrieval": {},
        "global_aggregate": {},
        "by_language": {},
        "by_dataset_and_language": {},
        "by_difficulty": {},
        "by_domain_cluster": {},
        "reranker_effect": {},
        "temporal_effect": {},
        "context": {},
        "answers": {},
        "real_user_telemetry": {},
        "negatives": {},
        "judge_agreement": {},
        "latency": {},
        "warnings": [],
    }
    pos_all = [r for r in rows if r["answerable"] and r.get("has_ground_truth", True)]
    real_user_rows = [r for r in rows if not r.get("has_ground_truth", True) and r["answerable"]]
    neg = [r for r in rows if not r["answerable"]]

    # 1. Global Aggregate across all ground-truth datasets (Synthetic 150 + FAQs 63)
    if pos_all:
        cl_all = [r["cluster"] for r in pos_all]
        ranks_all = [r.get("rank_final") for r in pos_all]
        ms_all = [rank_metrics(x, k) for x in ranks_all]
        rec_all = [r.get("recall_final", m["hit"]) for r, m in zip(pos_all, ms_all)]
        global_ans: Dict[str, Any] = {}
        answered_all = [r for r in pos_all if r.get("source") == "llm" and r.get("reference")]
        for m_name in ANSWER_METRICS:
            vs = [(r[m_name], r["cluster"]) for r in answered_all if _isnum(r.get(m_name))]
            if vs:
                global_ans[m_name] = _block([v for v, _ in vs], [c for _, c in vs], n_boot, seed)
        out["global_aggregate"] = {
            "n": len(pos_all),
            "hit@k": _block([m["hit"] for m in ms_all], cl_all, n_boot, seed),
            "recall@k": _block(rec_all, cl_all, n_boot, seed),
            "mrr@k": _block([m["rr"] for m in ms_all], cl_all, n_boot, seed),
            "answers": global_ans,
        }
        out["by_difficulty"] = slice_breakdown(pos_all, "difficulty", k, n_boot, seed)
        out["by_domain_cluster"] = slice_breakdown(pos_all, "domain_cluster", k, n_boot, seed)
        out["by_language"] = slice_breakdown(pos_all, "language", k, n_boot, seed)

    # 2. Per-Dataset Breakdown (synthetic_150 vs. faqs_63 vs. real_user_71)
    for s in sorted({r["set_name"] for r in rows if r["answerable"]}):
        pos = [r for r in rows if r["set_name"] == s and r["answerable"]]
        if not pos:
            continue
        has_gt = pos[0].get("has_ground_truth", True)
        out["n"][s] = {"queries": len(pos), "gold_chunks": len({r["cluster"] for r in pos})}

        if has_gt:
            out["retrieval"][s] = retrieval_block(pos, k, n_boot, seed)
            out["by_dataset_and_language"][s] = slice_breakdown(pos, "language", k, n_boot, seed)
            out["reranker_effect"][s] = paired_effect(pos, "rank_rrf", "rank_rerank", k, n_boot, seed)
            out["temporal_effect"][s] = paired_effect(pos, "rank_rerank", "rank_final", k, n_boot, seed)
            cl = [r["cluster"] for r in pos]
            ctx_vals = [
                float(r["ctx_recall"]) if _isnum(r.get("ctx_recall")) else (1.0 if r.get("ctx_hit") else 0.0)
                for r in pos
            ]
            ctx = {
                "gold_in_context": _block([1.0 if r.get("ctx_hit") else 0.0 for r in pos], cl, n_boot, seed),
                "proportional_ctx_recall": _block(ctx_vals, cl, n_boot, seed),
            }
            out["context"][s] = ctx

            answered = [r for r in pos if r.get("source") == "llm" and r.get("reference")]
            if answered:
                a: Dict[str, Any] = {
                    "n_answered": len(answered),
                    "fallback_rate": _block([1.0 if r["source"] == "fallback" else 0.0 for r in pos], cl, n_boot, seed),
                }
                for m in ANSWER_METRICS:
                    vs = [(r[m], r["cluster"]) for r in answered if _isnum(r.get(m))]
                    if vs:
                        a[m] = _block([v for v, _ in vs], [c for _, c in vs], n_boot, seed)
                out["answers"][s] = a

    # 3. Real-User Queries Telemetry (Untouched, single block)
    if real_user_rows:
        cl = [r["test_id"] for r in real_user_rows]
        ru: Dict[str, Any] = {
            "n": len(real_user_rows),
            "answered_rate": _block([1.0 if r.get("source") == "llm" else 0.0 for r in real_user_rows], cl, n_boot, seed),
            "fallback_rate": _block([1.0 if r.get("source") == "fallback" else 0.0 for r in real_user_rows], cl, n_boot, seed),
            "campus_detected_rate": _block([1.0 if r.get("detected_campus") else 0.0 for r in real_user_rows], cl, n_boot, seed),
        }
        for m in ("groundedness", "helpfulness", "context_sufficiency", "faithfulness", "answer_relevancy", "top_rerank_score"):
            vs = [(r[m], r["test_id"]) for r in real_user_rows if _isnum(r.get(m))]
            if vs:
                ru[m] = _block([v for v, _ in vs], [c for _, c in vs], n_boot, seed)
        out["real_user_telemetry"] = ru

    if neg:
        def _abst(r):
            return r.get("source") == "fallback" or r.get("abstained") is True
        kinds = sorted({r.get("negative_kind", "negative") for r in neg})
        nb: Dict[str, Any] = {"n": len(neg), "by_kind": {}}
        for kd in kinds:
            sub = [r for r in neg if r.get("negative_kind", "negative") == kd]
            cl = [r["cluster"] for r in sub]
            nb["by_kind"][kd] = {
                "n": len(sub),
                "abstained": _block([1.0 if _abst(r) else 0.0 for r in sub], cl, n_boot, seed),
                "unsupported_answer": _block([1.0 if r.get("asserted_unsupported_facts") else 0.0 for r in sub], cl, n_boot, seed),
            }
        pos_scores = [r["top_rerank_score"] if _isnum(r.get("top_rerank_score")) else float("-inf") for r in pos_all]
        neg_scores = [r["top_rerank_score"] if _isnum(r.get("top_rerank_score")) else float("-inf") for r in neg]
        nb["auc_answerable_vs_negative"] = auc_pos_vs_neg(pos_scores, neg_scores)
        nb["best_reranker_threshold"] = best_threshold(pos_scores, neg_scores)
        out["negatives"] = nb

    ans_rows = [r for r in pos_all if r.get("source") == "llm"]
    for a_key, b_key in AGREEMENT_PAIRS:
        val_a = [r.get(a_key) if _isnum(r.get(a_key)) else None for r in ans_rows]
        val_b = [r.get(b_key) if _isnum(r.get(b_key)) else None for r in ans_rows]
        if any(v is not None for v in val_a) and any(v is not None for v in val_b):
            rho = spearman(val_a, val_b)
            out["judge_agreement"][f"{a_key} vs {b_key}"] = rho
        else:
            out["judge_agreement"][f"{a_key} vs {b_key}"] = None

    for name, key in (("total_ms", "latency_ms"), ("retrieval_ms", "retrieval_latency_ms")):
        v = [r[key] for r in rows if _isnum(r.get(key))]
        out["latency"][name] = {"p50": percentile(v, 0.5), "p95": percentile(v, 0.95), "n": len(v)}
    return out


def _f(b: Optional[Dict[str, Any]], digits: int = 3) -> str:
    if not b or b.get("mean") is None:
        return "n/a"
    m = f"{b['mean']:.{digits}f}"
    if b.get("lo") is None:
        return m
    return f"{m} [{b['lo']:.{digits}f}-{b['hi']:.{digits}f}]"


def _table(headers: List[str], rows: List[List[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def render_markdown(s: Dict[str, Any], k: int) -> str:
    m = s["meta"]
    L: List[str] = [f"# RAG Evaluation Report - {m.get('org_name', '?')} (org_id={m.get('org_id')})", ""]
    L.append(f"- Evaluated at: {m.get('evaluated_at')}  |  top_k = {k}  |  query_mode = {m.get('query_mode', 'base')}  |  bootstrap = {m.get('n_boot')}")
    L.append(f"- Datasets: {', '.join(m.get('dataset_files', []))}  |  collection: {m.get('qdrant_collection')}")
    L.append(f"- Models: answer = {m.get('qa_model')}, judge = {m.get('judge_model')}, embedding = {m.get('embedding_model')}")
    if m.get("parity"):
        L.append(f"- Parity check (inspector vs production execute()): {m['parity']}")
    L.append("")

    # 1. Global Aggregate Summary
    if s.get("global_aggregate"):
        ga = s["global_aggregate"]
        L += [
            "## 1. Global Aggregated Performance (All Ground-Truth Datasets Combined)",
            "",
            f"- **Grand Total Evaluated Ground-Truth Queries**: {ga['n']}",
            f"- **Overall Hit@{k}**: {_f(ga['hit@k'])}",
            f"- **Overall Recall@{k}**: {_f(ga['recall@k'])}",
            f"- **Overall MRR@{k}**: {_f(ga['mrr@k'])}",
        ]
        if ga.get("answers") and "groundedness" in ga["answers"]:
            L.append(f"- **Overall Groundedness**: {_f(ga['answers']['groundedness'])}")
            L.append(f"- **Overall Completeness**: {_f(ga['answers'].get('completeness'))}")
            L.append(f"- **Overall Semantic Similarity**: {_f(ga['answers'].get('answer_semantic_similarity'))}")
        L.append("")

    # 2. Per-Dataset Retrieval Breakdown
    L += ["## 2. Per-Dataset Stage-by-Stage Retrieval", ""]
    for st, nn in s["n"].items():
        if st not in s["retrieval"]:
            continue
        L += [f"### Dataset: {st}  (n = {nn['queries']} queries)", ""]
        rows = []
        for name, _ in STAGES:
            b = s["retrieval"][st][name]
            rows.append([
                STAGE_LABELS[name],
                _f(b["hit@1"]),
                _f(b["hit@k"]),
                _f(b["precision@k"]),
                _f(b["recall@k"]),
                _f(b["all_hit@k"]),
                _f(b["mrr@k"]),
                _f(b["ndcg@k"]),
            ])
        L += [_table(["Stage", "Hit@1", f"Hit@{k}", f"Precision@{k}", f"Recall@{k}", f"All-Hit@{k}", f"MRR@{k}", f"nDCG@{k}"], rows), ""]

    # 3. Breakdown by Language (Global & Per-Dataset)
    if s.get("by_language"):
        L += [
            "## 3. Breakdown by Language (English vs. Tagalog vs. Taglish)",
            "",
            "*Note: Traditional lexical metrics (Token F1, ROUGE-L, BLEU) are computed strictly on English responses matching the English reference texts (`n/a` for Tagalog/Taglish).* ",
            "",
            "### 3a. Combined Ground-Truth Datasets by Language",
            "",
        ]
        rows = []
        for lang_name, b in s["by_language"].items():
            rows.append([
                lang_name,
                str(b["n"]),
                _f(b["hit@k"]),
                _f(b["recall@k"]),
                _f(b["mrr@k"]),
                _f(b["ctx_recall"]),
                _f(b.get("groundedness")),
                _f(b.get("completeness")),
                _f(b.get("answer_semantic_similarity")),
                _f(b.get("token_f1")),
                _f(b.get("rouge_l")),
                _f(b.get("bleu")),
            ])
        L += [_table(["Language", "n", f"Hit@{k}", f"Recall@{k}", f"MRR@{k}", "Ctx Recall", "Groundedness", "Completeness", "Semantic Sim", "Token F1 (EN)", "ROUGE-L (EN)", "BLEU (EN)"], rows), ""]

        for ds_name, lang_map in s.get("by_dataset_and_language", {}).items():
            L += [f"### 3b. {ds_name} by Language", ""]
            ds_rows = []
            for lang_name, b in lang_map.items():
                ds_rows.append([
                    lang_name,
                    str(b["n"]),
                    _f(b["hit@k"]),
                    _f(b["recall@k"]),
                    _f(b["mrr@k"]),
                    _f(b["ctx_recall"]),
                    _f(b.get("groundedness")),
                    _f(b.get("completeness")),
                    _f(b.get("answer_semantic_similarity")),
                    _f(b.get("token_f1")),
                ])
            L += [_table(["Language", "n", f"Hit@{k}", f"Recall@{k}", f"MRR@{k}", "Ctx Recall", "Groundedness", "Completeness", "Semantic Sim", "Token F1 (EN)"], ds_rows), ""]

    # 4. Breakdown by Difficulty Tier
    if s.get("by_difficulty"):
        L += ["## 4. Breakdown by Difficulty Tier (Easy / Medium / Hard)", ""]
        rows = []
        for diff in ("easy", "medium", "hard"):
            if diff not in s["by_difficulty"]:
                continue
            b = s["by_difficulty"][diff]
            rows.append([
                diff,
                str(b["n"]),
                _f(b["hit@k"]),
                _f(b["recall@k"]),
                _f(b["all_hit@k"]),
                _f(b["mrr@k"]),
                _f(b.get("completeness")),
                _f(b.get("answer_semantic_similarity")),
            ])
        L += [_table(["Tier", "n", f"Hit@{k}", f"Recall@{k}", f"All-Hit@{k}", f"MRR@{k}", "Completeness", "Semantic Sim"], rows), ""]

    # 5. Answer Quality Table
    if s.get("answers"):
        L += ["## 5. Per-Dataset Answer Quality Summary", ""]
        hdr = ["Metric"] + list(s["answers"].keys())
        rows = [
            ["answered n"] + [str(a["n_answered"]) for a in s["answers"].values()],
            ["fallback rate"] + [_f(a["fallback_rate"]) for a in s["answers"].values()],
        ]
        for mt in ANSWER_METRICS:
            rows.append([mt] + [_f(a.get(mt)) for a in s["answers"].values()])
        L += [_table(hdr, rows), ""]

    # 6. Real-User Queries Telemetry (Untouched block)
    if s.get("real_user_telemetry"):
        ru = s["real_user_telemetry"]
        L += [
            f"## 6. Real-User Queries Telemetry (n = {ru['n']} unlabeled queries, Reference-Free Metrics)",
            "",
            f"- Answered rate: {_f(ru['answered_rate'])}  |  Fallback rate: {_f(ru['fallback_rate'])}  |  Campus filter triggered: {_f(ru['campus_detected_rate'])}",
            f"- Reference-Free Groundedness: {_f(ru.get('groundedness'))}  |  Helpfulness: {_f(ru.get('helpfulness'))}  |  Context Sufficiency: {_f(ru.get('context_sufficiency'))}",
            f"- Ragas Faithfulness: {_f(ru.get('faithfulness'))}  |  Ragas Answer Relevancy: {_f(ru.get('answer_relevancy'))}",
            "",
        ]

    lat = s["latency"]
    if lat.get("total_ms", {}).get("n"):
        L += [
            "## 7. Latency",
            "",
            f"- Total p50/p95: {lat['total_ms']['p50']:.0f} / {lat['total_ms']['p95']:.0f} ms  |  Retrieval-only p50/p95: {lat['retrieval_ms']['p50']:.0f} / {lat['retrieval_ms']['p95']:.0f} ms",
            "",
        ]
    return "\n".join(L)


def headline(s: Dict[str, Any]) -> Dict[str, Any]:
    flat: Dict[str, Any] = {"org_id": s["meta"].get("org_id"), "org_name": s["meta"].get("org_name")}
    if s.get("global_aggregate"):
        ga = s["global_aggregate"]
        flat["global.hit@k"] = ga["hit@k"]["mean"]
        flat["global.recall@k"] = ga["recall@k"]["mean"]
        flat["global.mrr@k"] = ga["mrr@k"]["mean"]
    for st in s["retrieval"]:
        for stage in ("rrf", "rerank", "final"):
            for mt in ("hit@k", "recall@k", "mrr@k"):
                flat[f"{st}.{stage}.{mt}"] = s["retrieval"][st][stage][mt]["mean"]
    return flat