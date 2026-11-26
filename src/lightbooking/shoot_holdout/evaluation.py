from bisect import bisect_left
from fractions import Fraction
from itertools import groupby
from math import ceil, log
from statistics import mean

from ..settings import TARGET


# 现行布里尔分数容许线：新估法损失 ≤ 5/4 × 旧估法损失 + 3/200。
# 临界裁决用精确分数，舍入误差不能左右结论。
TOLERANCE_SLOPE = Fraction(5, 4)
TOLERANCE_INTERCEPT = Fraction(3, 200)


def margin_term(predicted, incumbent, actual):
    """同一结果下，新估法相对旧估法容许线的逐单余量（精确分数）。"""
    estimate = Fraction(predicted)
    reference = Fraction(incumbent)
    outcome = Fraction(actual)
    return (outcome - estimate) ** 2 - TOLERANCE_SLOPE * (outcome - reference) ** 2


def observed_margin(rows):
    """已确认结局单据的容许线余量合计；未知结局不参与此口径。"""
    return sum(
        (
            margin_term(row.predicted, row.incumbent, row.actual)
            for row in rows
            if row.occurred
        ),
        Fraction(0),
    )


def worst_case_margin(rows):
    """任一可能结局组合下的最不利余量合计。

    逐单独立取最不利结局后求和即得全局最不利：同一笔未知结局的单据，
    新旧估法按同一结果计分，再取让新估法最吃亏的那个结局。
    """
    total = Fraction(0)
    for row in rows:
        if row.occurred:
            total += margin_term(row.predicted, row.incumbent, row.actual)
        else:
            total += max(
                margin_term(row.predicted, row.incumbent, 0.0),
                margin_term(row.predicted, row.incumbent, 1.0),
            )
    return total


def exceeds_allowance(margin, count):
    """余量合计严格大于 容许截距 × 单数 即越线；精确比较，临界不翻转。"""
    return margin > TOLERANCE_INTERCEPT * count


def percentile(values, coverage):
    ordered = sorted(values)
    if not ordered:
        return None
    rank = min(len(ordered), max(1, ceil((len(ordered) + 1) * coverage)))
    return ordered[rank - 1]


def primary_loss(actual, predicted):
    return (actual - predicted) ** 2


def calibrate(records, prior):
    if (
        TARGET != "binary"
        or len(records) < 32
        or len({row.actual for row in records}) < 2
    ):
        return ()
    # 合并相邻反序概率区间，先按原始打分聚合再给局部基率小样本收缩。
    pools = []
    for prob, group in groupby(
        sorted(records, key=lambda row: row.predicted), key=lambda row: row.predicted
    ):
        entries = list(group)
        shrink = 0.65
        pools.append(
            [
                prob,
                sum(row.actual for row in entries) + shrink * prior,
                len(entries) + shrink,
            ]
        )
        while (
            len(pools) > 1 and pools[-2][1] * pools[-1][2] > pools[-1][1] * pools[-2][2]
        ):
            edge, yes, weight = pools.pop()
            lower = pools[-1]
            lower[:] = [edge, lower[1] + yes, lower[2] + weight]
    return tuple(
        (edge, min(0.995, max(0.005, yes / weight))) for edge, yes, weight in pools
    )


def apply_calibration(prediction, steps):
    if not steps:
        return prediction
    index = bisect_left([edge for edge, _ in steps], prediction)
    return steps[min(index, len(steps) - 1)][1]


def reliability(records, *, baseline=False):
    levels = [[0, 0.0, 0.0] for _ in range(5)]
    for row in records:
        prob = row.incumbent if baseline else row.predicted
        count = levels[min(4, max(0, int(prob * 5)))]
        count[0] += 1
        count[1] += prob
        count[2] += row.actual
    return [
        {
            "from": i / 5,
            "until": (i + 1) / 5,
            "count": count,
            "mean_score": estimate / count if count else None,
            "event_rate": hits / count if count else None,
        }
        for i, (count, estimate, hits) in enumerate(levels)
    ]


def paired_auc(rows, *, baseline=False):
    if not rows:
        return None
    prior_neg = 0
    gain = 0.0
    positives = sum(row.actual == 1 for row in rows)
    negatives = len(rows) - positives
    if not positives or not negatives:
        return None
    key = (lambda row: row.incumbent) if baseline else (lambda row: row.predicted)
    for _, tied in groupby(sorted(rows, key=key), key=key):
        rows_at_score = tuple(tied)
        pos = sum(row.actual == 1 for row in rows_at_score)
        neg = len(rows_at_score) - pos
        gain += pos * (prior_neg + neg / 2)
        prior_neg += neg
    return gain / (positives * negatives)


def censored_order(rows, *, baseline=False):
    pairs = 0
    correct = 0.0
    for ended in rows:
        if not ended.occurred:
            continue
        p = ended.incumbent if baseline else ended.predicted
        for later in rows:
            if later.actual <= ended.actual:
                continue
            other = later.incumbent if baseline else later.predicted
            pairs += 1
            correct += 1 if p < other else 0.5 if p == other else 0
    return correct / pairs if pairs else None


def evaluate(rows, radius):
    observed = [row for row in rows if row.occurred]
    actual = [row.actual for row in observed]
    losses = [primary_loss(row.actual, row.predicted) for row in observed]
    control = [primary_loss(row.actual, row.incumbent) for row in observed]
    result = {
        "support": len(rows),
        "observed_support": len(observed),
        "loss": mean(losses) if losses else None,
        "reference_loss": mean(control) if control else None,
        "average_actual": mean(actual) if actual else None,
        "mean_bias": mean(row.predicted - row.actual for row in observed)
        if observed
        else None,
    }
    if TARGET in {"binary", "anomaly"}:
        result.update(
            auc=paired_auc(observed),
            reference_auc=paired_auc(observed, baseline=True),
            reliability=reliability(observed),
        )
    elif TARGET == "censored":
        result.update(
            concordance=censored_order(rows),
            reference_concordance=censored_order(rows, baseline=True),
            censored=len(rows) - len(observed),
        )
    if radius is not None and observed:
        result["interval_coverage"] = sum(
            abs(row.actual - row.predicted) <= radius for row in observed
        ) / len(observed)
    return result
