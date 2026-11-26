from collections import defaultdict
from math import isfinite
from statistics import median

from ..lighting_holds.contracts import Outcome
from ..booking_signals.contracts import Signal
from ..settings import MODEL_LABEL, TARGET
from .challenge import score_distribution, stress_row
from .contracts import Fit, LearningRow
from .estimator import explain, infer, train


MIN_SUPPORT = 24


def fallback_value(rows: list[LearningRow]) -> float:
    if TARGET == "anomaly":
        return 0.0
    if TARGET == "binary":
        return (sum(row.y for row in rows) + 0.5) / (len(rows) + 1)
    eligible = [row.y for row in rows if row.outcome.occurred]
    return float(median(eligible)) if eligible else 0.0


def fit(signals: list[Signal], labels: dict[str, Outcome]) -> Fit:
    ordered = sorted(signals, key=lambda row: (row.record.day, row.record.case_id))
    if TARGET == "anomaly":
        # 训练只用历史特征。标签是事后告警记录，仅供回放。
        rows = [
            LearningRow(
                signal, Outcome(signal.record.case_id, signal.record.day, 0.0, True)
            )
            for signal in ordered
        ]
    else:
        rows = [
            LearningRow(signal, labels[signal.record.case_id])
            for signal in ordered
            if signal.record.case_id in labels
        ]
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.signal.record.group].append(row)
    incumbent = fallback_value(rows)
    benchmarks = {
        group: (len(items) * fallback_value(items) + 8 * incumbent) / (len(items) + 8)
        for group, items in grouped.items()
    }
    warnings = []
    state = None
    if len(rows) < MIN_SUPPORT:
        warnings.append("NOT_ENOUGH_TRAINING")
    elif TARGET == "binary" and len({row.y for row in rows}) < 2:
        warnings.append("SINGLE_OUTCOME_CLASS")
    else:
        state = train(rows)
        if state is None:
            warnings.append("MODEL_UNIDENTIFIABLE")
    return Fit(
        state,
        len(rows),
        incumbent,
        benchmarks,
        tuple(row.signal.record.case_id for row in rows),
        tuple(warnings),
    )


def bound(value: float) -> float:
    return (
        min(1.0, max(0.0, value))
        if TARGET in {"binary", "anomaly"}
        else max(0.0, value)
    )


def score(model: Fit, signal: Signal, *, baseline: bool = False) -> float:
    reference = model.by_group.get(signal.record.group, model.incumbent)
    if baseline or model.state is None:
        return bound(reference)
    estimate = infer(model.state, signal)
    return bound(estimate if isfinite(estimate) else reference)


def forecast_card(model, candidates, bank):
    return {
        **card(model),
        "forecast_summary": score_distribution(model, candidates, score),
        "stress": stress_row(model, candidates[0], bank, score) if candidates else None,
    }


def card(model: Fit) -> dict:
    return {
        "algorithm": MODEL_LABEL,
        "training_support": model.support,
        "incumbent": model.incumbent,
        "cohort_priors": model.by_group,
        "warnings": list(model.warnings),
        "parameters": explain(model.state) if model.state is not None else {},
    }
