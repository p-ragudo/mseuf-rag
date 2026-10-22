"""Statistics helpers: pure Python, no numpy/scipy needed."""
import math
import random
from collections import defaultdict
from typing import Any, Dict, Hashable, List, Optional, Sequence


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def cluster_bootstrap_mean(
    values: Sequence[float],
    clusters: Sequence[Hashable],
    n_boot: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """Mean with a percentile bootstrap CI that resamples CLUSTERS (e.g. gold chunks), not rows.

    Two questions generated from the same chunk are not independent; resampling rows would make the
    interval too narrow.
    """
    n = len(values)
    if n == 0:
        return {"mean": None, "lo": None, "hi": None, "n": 0}
    mean = sum(values) / n
    groups: Dict[Hashable, List[float]] = defaultdict(list)
    for v, c in zip(values, clusters):
        groups[c].append(v)
    sums = [sum(g) for g in groups.values()]
    cnts = [len(g) for g in groups.values()]
    m = len(sums)
    if m < 2 or n_boot <= 0:
        return {"mean": mean, "lo": None, "hi": None, "n": n}
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        s = 0.0
        c = 0
        for _ in range(m):
            j = rng.randrange(m)
            s += sums[j]
            c += cnts[j]
        boots.append(s / c)
    boots.sort()
    lo = boots[int((alpha / 2) * n_boot)]
    hi = boots[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return {"mean": mean, "lo": lo, "hi": hi, "n": n}


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts (b = only-A right, c = only-B right)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * p)


def auc_pos_vs_neg(pos: Sequence[float], neg: Sequence[float]) -> Optional[float]:
    """P(score_pos > score_neg), ties count 0.5."""
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for q in neg:
            wins += 1.0 if p > q else (0.5 if p == q else 0.0)
    return wins / (len(pos) * len(neg))


def best_threshold(pos: Sequence[float], neg: Sequence[float]) -> Optional[Dict[str, float]]:
    """Threshold maximising Youden's J = TPR - FPR (score >= t means 'answerable')."""
    if not pos or not neg:
        return None
    cands = sorted({s for s in list(pos) + list(neg) if s != float("-inf")})
    best = None
    for t in cands:
        tpr = sum(p >= t for p in pos) / len(pos)
        fpr = sum(q >= t for q in neg) / len(neg)
        j = tpr - fpr
        if best is None or j > best["youden_j"]:
            best = {"threshold": t, "tpr": tpr, "fpr": fpr, "youden_j": j}
    return best


def _avg_ranks(x: Sequence[float]) -> List[float]:
    order = sorted(range(len(x)), key=lambda i: x[i])
    ranks = [0.0] * len(x)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for t in range(i, j + 1):
            ranks[order[t]] = avg
        i = j + 1
    return ranks


def spearman(x: Sequence[Optional[float]], y: Sequence[Optional[float]]) -> Optional[float]:
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 3:
        return None
    xs = _avg_ranks([p[0] for p in pairs])
    ys = _avg_ranks([p[1] for p in pairs])
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    dy = math.sqrt(sum((b - my) ** 2 for b in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def percentile(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]
