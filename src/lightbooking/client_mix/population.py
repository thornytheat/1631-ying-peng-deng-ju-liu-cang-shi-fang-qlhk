from bisect import bisect_right
from math import log
from statistics import median

from ..settings import SIGNAL_NAMES


def _edges(reference):
    ranked = sorted(reference)
    return tuple(
        sorted(
            {ranked[len(ranked) * j // 5] for j in range(1, 5)}
            - {ranked[0], ranked[-1]}
        )
    )


def histogram(values, cutoffs):
    buckets = [0] * (len(cutoffs) + 1)
    for value in values:
        buckets[bisect_right(cutoffs, value)] += 1
    return buckets


def index_shift(reference, observed):
    if not reference or not observed:
        return {
            "psi": None,
            "reference": [],
            "current": [],
            "limits": [],
            "outside": None,
        }
    cutoffs = _edges(reference)
    before, after = histogram(reference, cutoffs), histogram(observed, cutoffs)
    # 半样本平滑保留空箱，常量参考另用越界比率，避免虚假的零漂移。
    size = len(before)
    proportions = [
        (
            (n + 0.5) / (len(reference) + 0.5 * size),
            (m + 0.5) / (len(observed) + 0.5 * size),
        )
        for n, m in zip(before, after)
    ]
    psi = sum((q - p) * log(q / p) for p, q in proportions)
    low, high = min(reference), max(reference)
    pad = max(1e-8, (high - low) * 0.04)
    return {
        "psi": psi,
        "limits": list(cutoffs),
        "reference": before,
        "current": after,
        "outside": sum(v < low - pad or v > high + pad for v in observed)
        / len(observed),
        "reference_median": median(reference),
        "recent_median": median(observed),
    }


def compare(history, batch):
    return {
        name: index_shift(
            [case.vector[i] for case in history], [case.vector[i] for case in batch]
        )
        for i, name in enumerate(SIGNAL_NAMES)
    }


def missing_rate(rows):
    return sum(bool(row.missing) for row in rows) / len(rows) if rows else 0.0


def extreme_signal(signal, reference):
    if not reference:
        return []
    triggers = []
    for i, name in enumerate(SIGNAL_NAMES):
        prior = [row.vector[i] for row in reference]
        span = max(prior) - min(prior)
        value = signal.vector[i]
        headroom = max(span * 0.28, 1e-6)
        if value < min(prior) - headroom or value > max(prior) + headroom:
            triggers.append(name)
    return triggers
