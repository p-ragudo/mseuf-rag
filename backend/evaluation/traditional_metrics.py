import math
import re
import string
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence


def normalize_text(text: str) -> str:
    """Lowercase, remove punctuation, articles, and extra whitespace (SQuAD standard)."""
    text = (text or "").lower()
    text = "".join(ch for ch in text if ch not in set(string.punctuation))
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def tokenize(text: str) -> List[str]:
    norm = normalize_text(text)
    return norm.split() if norm else []


def compute_token_f1(prediction: str, reference: str) -> Dict[str, float]:
    """Computes token-level Precision, Recall, and F1 between prediction and reference."""
    pred_tokens = tokenize(prediction)
    ref_tokens = tokenize(reference)

    if not pred_tokens and not ref_tokens:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not pred_tokens or not ref_tokens:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    common = Counter(pred_tokens) & Counter(ref_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    precision = num_same / len(pred_tokens)
    recall = num_same / len(ref_tokens)
    f1 = (2 * precision * recall) / (precision + recall)
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _get_ngrams(tokens: Sequence[str], n: int) -> Counter:
    if len(tokens) < n:
        return Counter()
    return Counter(tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))


def compute_bleu(prediction: str, reference: str, max_n: int = 4) -> float:
    """Computes smoothed corpus/sentence BLEU-4 score (0.0 to 1.0)."""
    pred_tokens = tokenize(prediction)
    ref_tokens = tokenize(reference)

    if not pred_tokens or not ref_tokens:
        return 0.0

    precisions: List[float] = []
    for n in range(1, max_n + 1):
        pred_ngrams = _get_ngrams(pred_tokens, n)
        ref_ngrams = _get_ngrams(ref_tokens, n)
        total_pred = sum(pred_ngrams.values())

        if total_pred == 0:
            precisions.append(0.0)
            continue

        clipped_matches = sum(
            min(count, ref_ngrams[gram]) for gram, count in pred_ngrams.items()
        )
        # Add-1 smoothing for higher order n-grams so short valid answers don't zero out
        if n > 1:
            p_n = (clipped_matches + 1.0) / (total_pred + 1.0)
        else:
            p_n = clipped_matches / total_pred
        precisions.append(p_n)

    if any(p <= 0 for p in precisions):
        return 0.0

    log_avg = sum(math.log(p) for p in precisions) / max_n

    # Brevity penalty
    c = len(pred_tokens)
    r = len(ref_tokens)
    bp = 1.0 if c > r else math.exp(1.0 - (r / max(c, 1)))

    return round(float(bp * math.exp(log_avg)), 4)


def compute_rouge_n(prediction: str, reference: str, n: int = 1) -> float:
    """Computes ROUGE-N F1 score."""
    pred_tokens = tokenize(prediction)
    ref_tokens = tokenize(reference)
    if not pred_tokens or not ref_tokens:
        return 0.0

    pred_ngrams = _get_ngrams(pred_tokens, n)
    ref_ngrams = _get_ngrams(ref_tokens, n)

    if not pred_ngrams or not ref_ngrams:
        return 0.0

    overlap = sum((pred_ngrams & ref_ngrams).values())
    if overlap == 0:
        return 0.0

    prec = overlap / sum(pred_ngrams.values())
    rec = overlap / sum(ref_ngrams.values())
    return round((2 * prec * rec) / (prec + rec), 4)


def _lcs_length(x: Sequence[str], y: Sequence[str]) -> int:
    """Dynamic programming Longest Common Subsequence for token lists."""
    m, n = len(x), len(y)
    if m == 0 or n == 0:
        return 0
    # Cap token length at 600 to keep DP fast
    x = x[:600]
    y = y[:600]
    m, n = len(x), len(y)

    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        xi = x[i - 1]
        for j in range(1, n + 1):
            if xi == y[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = prev[j] if prev[j] >= curr[j - 1] else curr[j - 1]
        prev = curr
    return prev[n]


def compute_rouge_l(prediction: str, reference: str) -> float:
    """Computes ROUGE-L F1 score based on Longest Common Subsequence."""
    pred_tokens = tokenize(prediction)
    ref_tokens = tokenize(reference)
    if not pred_tokens or not ref_tokens:
        return 0.0

    lcs = _lcs_length(pred_tokens, ref_tokens)
    if lcs == 0:
        return 0.0

    prec = lcs / len(pred_tokens)
    rec = lcs / len(ref_tokens)
    return round((2 * prec * rec) / (prec + rec), 4)


def compute_all_lexical_metrics(prediction: str, reference: str) -> Dict[str, float]:
    f1_Stats = compute_token_f1(prediction, reference)
    return {
        "token_precision": f1_Stats["precision"],
        "token_recall": f1_Stats["recall"],
        "token_f1": f1_Stats["f1"],
        "bleu": compute_bleu(prediction, reference),
        "rouge_1": compute_rouge_n(prediction, reference, n=1),
        "rouge_2": compute_rouge_n(prediction, reference, n=2),
        "rouge_l": compute_rouge_l(prediction, reference),
    }


def compute_ranking_metrics(
    ranked_chunk_ids: List[int],
    ranked_urls: List[str],
    gt_chunk_ids: List[int],
    gt_url: str,
    k: int = 5,
) -> Dict[str, Any]:
    """
    Computes Hit@K, MRR, NDCG@K, and 1-based exact rank for a candidate list
    (used both Before Cross-Encoder and After Cross-Encoder).
    """
    gt_id_set = set(int(cid) for cid in gt_chunk_ids if cid is not None)

    # 1. Exact Chunk Rank ( across full candidate pool )
    chunk_rank: Optional[int] = None
    for idx, cid in enumerate(ranked_chunk_ids, start=1):
        if cid in gt_id_set:
            chunk_rank = idx
            break

    # 2. URL Rank ( across full candidate pool )
    url_rank: Optional[int] = None
    for idx, u in enumerate(ranked_urls, start=1):
        if u and u == gt_url:
            url_rank = idx
            break

    # Use chunk_rank as primary; fallback to url_rank if chunk was merged/re-indexed
    effective_rank = chunk_rank if chunk_rank is not None else url_rank

    hit_at_k = 1.0 if (effective_rank is not None and effective_rank <= k) else 0.0
    rr = round(1.0 / effective_rank, 4) if effective_rank is not None else 0.0
    rr_at_k = round(1.0 / effective_rank, 4) if (effective_rank is not None and effective_rank <= k) else 0.0

    # Binary NDCG@K: for single ground-truth target, IDCG = 1.0, DCG = 1 / log2(rank + 1)
    if effective_rank is not None and effective_rank <= k:
        ndcg_at_k = round(1.0 / math.log2(effective_rank + 1), 4)
    else:
        ndcg_at_k = 0.0

    return {
        "chunk_rank": chunk_rank,
        "url_rank": url_rank,
        "effective_rank": effective_rank,
        "hit_at_k": hit_at_k,
        "rr": rr,
        "rr_at_k": rr_at_k,
        "ndcg_at_k": ndcg_at_k,
    }