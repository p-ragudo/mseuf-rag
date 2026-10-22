"""Turns per-query rows into summary statistics (with confidence intervals) and a markdown report. Pure Python."""
import math
from typing import Any, Callable, Dict, List, Optional

from evaluation.stats import (
    auc_pos_vs_neg, best_threshold, cluster_bootstrap_mean, mcnemar_exact, percentile, spearman,
)
from evaluation.traditional_metrics import rank_metrics

STAGES = [("dense", "rank_dense"), ("sparse", "rank_sparse"), ("rrf", "rank_rrf"),
          ("rerank", "rank_rerank"), ("final", "rank_final")]
STAGE_LABELS = {
    "dense": "Dense only (question vectors)", "sparse": "Sparse only (BM25 on chunk text)",
    "rrf": "Hybrid RRF (before reranker)", "rerank": "After cross-encoder (reranker only)",
    "final": "Final (threshold + temporal + top-k)",
}
ANSWER_METRICS = ["groundedness", "completeness", "helpfulness", "context_sufficiency", "faithfulness",
                  "answer_relevancy", "context_precision", "context_recall", "answer_correctness",
                  "token_recall", "token_f1", "rouge_l"]
AGREEMENT_PAIRS = [("faithfulness", "groundedness"), ("answer_correctness", "completeness"),
                   ("context_recall", "context_sufficiency"), ("answer_relevancy", "helpfulness")]


def _isnum(x: Any) -> bool:
    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


def _block(values: List[float], clusters: List[Any], n_boot: int, seed: int) -> Dict[str, Any]:
    return cluster_bootstrap_mean(values, clusters, n_boot=n_boot, seed=seed)


def retrieval_block(pos: List[Dict[str, Any]], k: int, n_boot: int, seed: int) -> Dict[str, Dict[str, Any]]:
    cl = [r["cluster"] for r in pos]
    out: Dict[str, Dict[str, Any]] = {}
    for name, key in STAGES:
        ranks = [r.get(key) for r in pos]
        ms = [rank_metrics(x, k) for x in ranks]
        out[name] = {
            "hit@1": _block([1.0 if (x is not None and x <= 1) else 0.0 for x in ranks], cl, n_boot, seed),
            "hit@k": _block([m["hit"] for m in ms], cl, n_boot, seed),
            "mrr@k": _block([m["rr"] for m in ms], cl, n_boot, seed),
            "ndcg@k": _block([m["ndcg"] for m in ms], cl, n_boot, seed),
            "in_pool": _block([1.0 if x is not None else 0.0 for x in ranks], cl, n_boot, seed),
        }
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
        "rescued": rescued, "harmed": harmed,
        "both_hit": sum(1 for a, b in zip(a_hit, b_hit) if a and b),
        "both_miss": sum(1 for a, b in zip(a_hit, b_hit) if not a and not b),
        "delta_hit@k": _block([b - a for a, b in zip(a_hit, b_hit)], cl, n_boot, seed),
        "delta_mrr@k": _block([rank_metrics(b, k)["rr"] - rank_metrics(a, k)["rr"] for a, b in zip(a_rank, b_rank)],
                              cl, n_boot, seed),
        "mcnemar_p": mcnemar_exact(rescued, harmed),
    }


def _vals(rows, key):
    return [r.get(key) for r in rows]


def summarize(rows: List[Dict[str, Any]], k: int, n_boot: int = 1000, seed: int = 0,
              meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = meta or {}
    out: Dict[str, Any] = {"meta": meta, "n": {}, "retrieval": {}, "reranker_effect": {}, "temporal_effect": {},
                           "context": {}, "answers": {}, "negatives": {}, "judge_agreement": {}, "latency": {},
                           "warnings": []}
    pos_all = [r for r in rows if r["answerable"]]
    neg = [r for r in rows if not r["answerable"]]

    for s in sorted({r["set_name"] for r in rows if r["answerable"]}):
        pos = [r for r in pos_all if r["set_name"] == s]
        out["n"][s] = {"queries": len(pos), "gold_chunks": len({r["cluster"] for r in pos})}
        out["retrieval"][s] = retrieval_block(pos, k, n_boot, seed)
        out["reranker_effect"][s] = paired_effect(pos, "rank_rrf", "rank_rerank", k, n_boot, seed)
        out["temporal_effect"][s] = paired_effect(pos, "rank_rerank", "rank_final", k, n_boot, seed)
        cl = [r["cluster"] for r in pos]
        ctx = {"gold_in_context": _block([1.0 if r.get("ctx_hit") else 0.0 for r in pos], cl, n_boot, seed)}
        ctx["final_hit_but_not_in_context"] = sum(
            1 for r in pos if r.get("rank_final") is not None and r["rank_final"] <= k and not r.get("ctx_hit"))
        out["context"][s] = ctx

        # ---- answers (only if the answer stage ran) ----
        answered = [r for r in pos if r.get("source") == "llm" and r.get("reference")]
        with_resp = [r for r in pos if r.get("answer_stage")]
        if with_resp:
            a: Dict[str, Any] = {"n_answered": len(answered),
                                 "fallback_rate": _block([1.0 if r["source"] == "fallback" else 0.0 for r in pos], cl, n_boot, seed)}
            for m in ANSWER_METRICS:
                vs = [(r[m], r["cluster"]) for r in answered if _isnum(r.get(m))]
                a[m] = _block([v for v, _ in vs], [c for _, c in vs], n_boot, seed)
            # fallback rows count as 0 completeness (the user got nothing)
            ref_rows = [r for r in pos if r.get("reference") and r.get("source") in ("llm", "fallback")]
            vs2 = [((r["completeness"] if r["source"] == "llm" and _isnum(r.get("completeness")) else 0.0), r["cluster"])
                   for r in ref_rows if r["source"] == "fallback" or _isnum(r.get("completeness"))]
            a["completeness_unconditional"] = _block([v for v, _ in vs2], [c for _, c in vs2], n_boot, seed)
            out["answers"][s] = a

    # ---- negatives / abstention + reranker-score separability ----
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

    # ---- judge agreement (two independent judge implementations should correlate) ----
    ans_rows = [r for r in pos_all if r.get("source") == "llm"]
    for a_key, b_key in AGREEMENT_PAIRS:
        rho = spearman([r.get(a_key) if _isnum(r.get(a_key)) else None for r in ans_rows],
                       [r.get(b_key) if _isnum(r.get(b_key)) else None for r in ans_rows])
        out["judge_agreement"][f"{a_key} vs {b_key}"] = rho

    for name, key in (("total_ms", "latency_ms"), ("retrieval_ms", "retrieval_latency_ms")):
        v = [r[key] for r in rows if _isnum(r.get(key))]
        out["latency"][name] = {"p50": percentile(v, 0.5), "p95": percentile(v, 0.95), "n": len(v)}

    # ---- automatic cautions ----
    for s, nn in out["n"].items():
        if nn["queries"] < 100:
            out["warnings"].append(f"Set '{s}': only {nn['queries']} queries from {nn['gold_chunks']} gold chunks; "
                                   "differences of a few points are within noise (see CIs).")
    if meta.get("judge_model") and meta["judge_model"] in (meta.get("qa_model"), meta.get("curator_model")):
        out["warnings"].append("The judge model equals the answer or curator model: expect self-preference bias.")
    if meta.get("stale_skipped"):
        out["warnings"].append(f"{meta['stale_skipped']} records skipped because their gold chunk changed/disappeared "
                               "since the dataset was generated.")
    return out


# ---------------------------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------------------------

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
    L: List[str] = [f"# RAG evaluation - {m.get('org_name', '?')} (org_id={m.get('org_id')})", ""]
    L.append(f"- Evaluated at: {m.get('evaluated_at')}  |  top_k = {k}  |  bootstrap resamples = {m.get('n_boot')}")
    L.append(f"- Datasets: {', '.join(m.get('dataset_files', []))}  |  collection: {m.get('qdrant_collection')}")
    L.append(f"- Models: answer = {m.get('qa_model')}, judge = {m.get('judge_model')}, embedding = {m.get('embedding_model')}")
    if m.get("parity"):
        L.append(f"- Parity check (inspector vs production execute()): {m['parity']}")
    L.append("- Intervals are 95% percentile bootstrap CIs resampling gold chunks.")
    L.append("")
    if s["warnings"]:
        L += ["## Cautions", ""] + [f"- {w}" for w in s["warnings"]] + [""]

    L += ["## 1. Retrieval (gold chunk, chunk level)", "",
          "A hit = the gold chunk (or an exact same-campus duplicate) is in the list. Another chunk from the same page is a MISS.", ""]
    for st, nn in s["n"].items():
        L += [f"### Set: {st}  (n = {nn['queries']} queries, {nn['gold_chunks']} gold chunks)", ""]
        rows = []
        for name, _ in STAGES:
            b = s["retrieval"][st][name]
            rows.append([STAGE_LABELS[name], _f(b["hit@1"]), _f(b["hit@k"]), _f(b["mrr@k"]), _f(b["ndcg@k"]), _f(b["in_pool"])])
        L += [_table(["Stage", "Hit@1", f"Hit@{k}", f"MRR@{k}", f"nDCG@{k}", "Gold anywhere in list"], rows), ""]

    L += ["## 2. Does the reranker help? (paired, same queries)", "",
          "rescued = gold outside top-k before, inside after; harmed = the reverse. p = exact McNemar test on the discordant pairs.", ""]
    rows = []
    for st, e in s["reranker_effect"].items():
        rows.append([st, str(e["rescued"]), str(e["harmed"]), _f(e["delta_hit@k"]), _f(e["delta_mrr@k"]), f"{e['mcnemar_p']:.3f}"])
    L += [_table(["Set", "Rescued", "Harmed", f"Delta Hit@{k}", f"Delta MRR@{k}", "McNemar p"], rows), ""]
    L += ["Ceiling: the reranker can only reorder the pool it receives, so 'Gold anywhere in list' for the RRF row above is its upper bound.", ""]
    rows = [[st, str(e["rescued"]), str(e["harmed"]), _f(e["delta_hit@k"])] for st, e in s["temporal_effect"].items()]
    L += ["Threshold + temporal resolution + top-k cut (rerank -> final):", "", _table(["Set", "Rescued", "Harmed", f"Delta Hit@{k}"], rows), ""]

    L += ["## 3. What the answer LLM actually saw", "",
          "Gold chunk text present in the expanded (small-to-big) contexts:", ""]
    rows = [[st, _f(c["gold_in_context"]), str(c["final_hit_but_not_in_context"])] for st, c in s["context"].items()]
    L += [_table(["Set", "Gold in contexts", "Final hit but NOT in contexts (expander/matching problem)"], rows), ""]

    if s["answers"]:
        L += ["## 4. Answer quality (rows the pipeline answered; judge scores 0-1)", ""]
        hdr = ["Metric"] + list(s["answers"].keys())
        rows = [["answered n"] + [str(a["n_answered"]) for a in s["answers"].values()],
                ["fallback rate (no answer)"] + [_f(a["fallback_rate"]) for a in s["answers"].values()],
                ["completeness incl. fallback=0"] + [_f(a["completeness_unconditional"]) for a in s["answers"].values()]]
        for mt in ANSWER_METRICS:
            rows.append([mt] + [_f(a.get(mt)) for a in s["answers"].values()])
        L += [_table(hdr, rows), "",
              "Judge metrics are LLM opinions against an LLM-written reference. Token/ROUGE rows are weak secondary signals.", ""]

    if s["negatives"]:
        nb = s["negatives"]
        L += ["## 5. Unanswerable questions (abstention)", "",
              "Correct behaviour = decline. 'Unsupported answer' = it asserted facts that are not in the contexts.", ""]
        rows = [[kd, str(v["n"]), _f(v["abstained"]), _f(v["unsupported_answer"])] for kd, v in nb["by_kind"].items()]
        L += [_table(["Kind", "n", "Abstained", "Unsupported answer"], rows), ""]
        if nb.get("auc_answerable_vs_negative") is not None:
            L.append(f"- AUC of top reranker score separating answerable from unanswerable: {nb['auc_answerable_vs_negative']:.3f}")
        bt = nb.get("best_reranker_threshold")
        if bt:
            L.append(f"- Score threshold with best TPR-FPR: {bt['threshold']:.3f} (keeps {bt['tpr']:.0%} of answerable, lets through "
                     f"{bt['fpr']:.0%} of unanswerable). Candidate for settings.reranker_score_threshold (currently unset); validate on more data.")
        L.append("")

    ag = {k_: v for k_, v in s["judge_agreement"].items() if v is not None}
    if ag:
        L += ["## 6. Judge agreement (Spearman rho between two independent judges of the same quality)", ""]
        L += [f"- {k_}: {v:.2f}" for k_, v in ag.items()] + [""]
    lat = s["latency"]
    if lat.get("total_ms", {}).get("n"):
        L += ["## 7. Latency (single-user, sequential)", "",
              f"- total p50/p95: {lat['total_ms']['p50']:.0f} / {lat['total_ms']['p95']:.0f} ms; "
              f"retrieval-only p50/p95: {lat['retrieval_ms']['p50']:.0f} / {lat['retrieval_ms']['p95']:.0f} ms", ""]
    return "\n".join(L)


def headline(s: Dict[str, Any]) -> Dict[str, Any]:
    """Flat dict of point estimates for the multi-tenant rollup CSV."""
    flat: Dict[str, Any] = {"org_id": s["meta"].get("org_id"), "org_name": s["meta"].get("org_name")}
    for st in s["retrieval"]:
        for stage in ("rrf", "rerank", "final"):
            for mt in ("hit@k", "mrr@k"):
                flat[f"{st}.{stage}.{mt}"] = s["retrieval"][st][stage][mt]["mean"]
        flat[f"{st}.gold_in_context"] = s["context"][st]["gold_in_context"]["mean"]
    for st, a in s["answers"].items():
        for mt in ("faithfulness", "answer_correctness", "groundedness", "completeness"):
            flat[f"{st}.{mt}"] = a[mt]["mean"]
    return flat
