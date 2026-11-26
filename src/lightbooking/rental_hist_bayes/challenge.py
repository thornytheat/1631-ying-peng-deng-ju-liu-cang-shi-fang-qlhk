from dataclasses import replace
from math import fsum, isfinite
from statistics import median

from ..settings import SIGNAL_NAMES


def stress_row(fitted, row, bank, scoring):
    base = scoring(fitted, row)
    effects = []
    for i, name in enumerate(SIGNAL_NAMES):
        current = list(row.normalized)
        raw = list(row.vector)
        scale = bank.global_scale
        raw[i] = raw[i] * 0.9 + scale.centers[i] * 0.1
        current[i] = max(
            -12.0, min(12.0, (raw[i] - scale.centers[i]) / scale.slopes[i])
        )
        adjusted = replace(row, vector=tuple(raw), normalized=tuple(current))
        estimate = scoring(fitted, adjusted)
        effects.append(
            {
                "signal": name,
                "score_delta": estimate - base,
                "scenario": "单特征向历史中位数收缩一成",
            }
        )
    return {"case_id": row.record.case_id, "score": base, "comparison": effects}


def score_distribution(fitted, candidates, scoring):
    points = [scoring(fitted, signal) for signal in candidates]
    if not points:
        return {"minimum": None, "maximum": None, "median": None, "average": None}
    return {
        "minimum": min(points),
        "maximum": max(points),
        "median": median(points),
        "average": fsum(points) / len(points),
    }
