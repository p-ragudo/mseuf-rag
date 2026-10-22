"""Rank metrics, gold-in-context matching and lexical overlap metrics. No app imports."""
import math
import re
import string
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from evaluation.common import normalize_ws

# --------------------------------------------------------------------------------------
# Ranking (chunk level). A hit means the GOLD CHUNK (or an exact same-campus duplicate of it)
# is in the list. A different chunk from the same page is NOT a hit.
# --------------------------------------------------------------------------------------


def first_rank(ranked_ids: Sequence[Optional[int]], gold_ids: Sequence[int]) -> Optional[int]:
    gold = {int(g) for g in gold_ids if g is not None}
    if not gold:
        return None
    for idx, cid in enumerate(ranked_ids, start=1):
        if cid is not None and int(cid) in gold:
            return idx
    return None


def first_url_rank(ranked_urls: Sequence[str], gold_url: Optional[str]) -> Optional[int]:
    """Diagnostic only. Never used for headline metrics (a page has many chunks)."""
    if not gold_url:
        return None
    for idx, u in enumerate(ranked_urls, start=1):
        if u and u == gold_url:
            return idx
    return None


def rank_metrics(rank: Optional[int], k: int) -> Dict[str, float]:
    """Hit@k, RR@k and binary NDCG@k for ONE relevant item (IDCG = 1)."""
    if rank is None or rank > k:
        return {"hit": 0.0, "rr": 0.0, "ndcg": 0.0}
    return {"hit": 1.0, "rr": 1.0 / rank, "ndcg": 1.0 / math.log2(rank + 1)}


# --------------------------------------------------------------------------------------
# Did the LLM actually SEE the gold chunk?  (small-to-big expansion merges neighbours, so we
# match text anchors instead of ids.)
# --------------------------------------------------------------------------------------


def gold_body(text: str) -> str:
    lines = (text or "").strip().splitlines()
    if lines and lines[0].startswith("Section:"):
        return "\n".join(lines[1:]).strip()
    return (text or "").strip()


def gold_anchors(text: str, n: int = 3, length: int = 100) -> List[str]:
    body = normalize_ws(gold_body(text))
    if not body:
        return []
    if len(body) <= length:
        return [body]
    anchors = []
    for i in range(n):
        start = int((len(body) - length) * i / max(1, n - 1))
        anchors.append(body[start : start + length])
    return anchors


def gold_in_contexts(
    gold_text: str, contexts: Sequence[str], min_fraction: float = 2 / 3
) -> Tuple[bool, Optional[int]]:
    """True if >= min_fraction of the gold chunk's 3 anchors appear in one retrieved context."""
    anchors = gold_anchors(gold_text)
    if not anchors:
        return False, None
    for idx, ctx in enumerate(contexts, start=1):
        norm_ctx = normalize_ws(ctx)
        found = sum(1 for a in anchors if a in norm_ctx)
        if found / len(anchors) >= min_fraction:
            return True, idx
    return False, None


# --------------------------------------------------------------------------------------
# Lexical metrics. Weak evidence of answer quality (both texts are LLM-written); keep them as
# secondary / sanity metrics only.
# --------------------------------------------------------------------------------------

_PUNCT = set(string.punctuation)


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"(?<=\d)\s*[-\u2013\u2014/]\s*(?=\d)", " ", text)  # 2025-2026 -> 2025 2026
    text = text.replace("\u2013", " ").replace("\u2014", " ")
    text = "".join(ch for ch in text if ch not in _PUNCT)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def tokenize(text: str) -> List[str]:
    norm = normalize_text(text)
    return norm.split() if norm else []


def compute_token_f1(prediction: str, reference: str) -> Dict[str, float]:
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
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def _get_ngrams(tokens: Sequence[str], n: int) -> Counter:
    if len(tokens) < n:
        return Counter()
    return Counter(tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))


def compute_bleu(prediction: str, reference: str, max_n: int = 4) -> float:
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
        clipped = sum(min(count, ref_ngrams[g]) for g, count in pred_ngrams.items())
        precisions.append((clipped + 1.0) / (total_pred + 1.0) if n > 1 else clipped / total_pred)
    if any(p <= 0 for p in precisions):
        return 0.0
    log_avg = sum(math.log(p) for p in precisions) / max_n
    c, r = len(pred_tokens), len(ref_tokens)
    bp = 1.0 if c > r else math.exp(1.0 - (r / max(c, 1)))
    return round(float(bp * math.exp(log_avg)), 4)


def compute_rouge_n(prediction: str, reference: str, n: int = 1) -> float:
    pred_tokens = tokenize(prediction)
    ref_tokens = tokenize(reference)
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
    x = x[:600]
    y = y[:600]
    m, n = len(x), len(y)
    if m == 0 or n == 0:
        return 0
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
    pred_tokens = tokenize(prediction)
    ref_tokens = tokenize(reference)
    if not pred_tokens or not ref_tokens:
        return 0.0
    lcs = _lcs_length(pred_tokens, ref_tokens)
    if lcs == 0:
        return 0.0
    prec = lcs / min(len(pred_tokens), 600)
    rec = lcs / min(len(ref_tokens), 600)
    return round((2 * prec * rec) / (prec + rec), 4)


def compute_all_lexical_metrics(prediction: str, reference: str) -> Dict[str, float]:
    f1 = compute_token_f1(prediction, reference)
    return {
        "token_precision": f1["precision"],
        "token_recall": f1["recall"],
        "token_f1": f1["f1"],
        "bleu": compute_bleu(prediction, reference),
        "rouge_1": compute_rouge_n(prediction, reference, n=1),
        "rouge_2": compute_rouge_n(prediction, reference, n=2),
        "rouge_l": compute_rouge_l(prediction, reference),
    }
