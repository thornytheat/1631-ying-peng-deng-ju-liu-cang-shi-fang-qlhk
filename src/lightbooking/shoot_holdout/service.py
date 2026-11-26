from collections import defaultdict
from dataclasses import replace

from ..lighting_holds.service import known_labels
from ..rental_hist_bayes.service import score
from ..settings import METRIC_LABEL, TARGET
from .contracts import Assessment, Folds, Paired, ScoreCard
from .evaluation import (
    apply_calibration,
    calibrate,
    evaluate,
    exceeds_allowance,
    observed_margin,
    percentile,
    worst_case_margin,
)


def split(as_of):
    return Folds(as_of - 63, as_of - 34, as_of - 11, as_of)


def paired(signals, intake, after, before, reference_day, model, *, include_unknown=False):
    labels = known_labels(intake, reference_day)
    rows = []
    for item in signals:
        if not (after <= item.record.day < before) or item.record.arrived > reference_day:
            continue
        outcome = labels.get(item.record.case_id)
        if outcome is None:
            # 提前撤仓、截止日前没有结案回执的单据结局未知；
            # 不参与训练和校准，只在回放段按未知结局成对计分。
            if not include_unknown or TARGET != "binary":
                continue
            rows.append(
                Paired(
                    item.record.case_id,
                    item.record.group,
                    -1.0,
                    score(model, item),
                    score(model, item, baseline=True),
                    False,
                )
            )
            continue
        rows.append(
            Paired(
                item.record.case_id,
                item.record.group,
                outcome.value,
                score(model, item),
                score(model, item, baseline=True),
                outcome.occurred,
            )
        )
    return rows


def backcheck(signals, intake, bounds, model):
    calibration = paired(
        signals,
        intake,
        bounds.train_before,
        bounds.calibrate_before,
        bounds.calibrate_before - 1,
        model,
    )
    # 回放段纳入提前撤仓的未知结局单据：新旧估法对同一笔按同一结果计分。
    holdout = paired(
        signals,
        intake,
        bounds.calibrate_before,
        bounds.validate_before,
        bounds.snapshot - 1,
        model,
        include_unknown=True,
    )
    steps = calibrate(calibration, model.incumbent)
    evidence = [
        replace(row, predicted=apply_calibration(row.predicted, steps))
        for row in holdout
    ]
    radius = (
        None
        if TARGET in {"binary", "anomaly"} or len(calibration) < 16
        else percentile(
            [abs(row.actual - row.predicted) for row in calibration if row.occurred],
            0.80,
        )
    )
    overall = evaluate(evidence, radius)
    observed = [row for row in evidence if row.occurred]
    if TARGET == "anomaly":
        rank = overall["auc"]
        passed = rank is not None and rank >= 0.48
    else:
        passed = bool(observed) and not exceeds_allowance(
            observed_margin(observed), len(observed)
        )
    grouped = defaultdict(list)
    for row in evidence:
        grouped[row.group].append(row)
    groups = {}
    fragile = []
    for name, rows in sorted(grouped.items()):
        entry = evaluate(rows, radius)
        entry["censored"] = sum(1 for row in rows if not row.occurred)
        if TARGET == "binary":
            # 任一可能结局组合下越线的棚组整组转人工。
            margin = worst_case_margin(rows)
            entry["worst_case_margin"] = float(margin)
            entry["worst_case_exceeds"] = exceeds_allowance(margin, len(rows))
            if entry["worst_case_exceeds"]:
                fragile.append(name)
        groups[name] = entry
    report = {
        "metric": METRIC_LABEL,
        "overall": overall,
        "groups": groups,
        "fragile_groups": fragile,
        "calibration_cases": len(calibration),
        "holdout_cases": len(holdout),
        "holdout_days": [bounds.calibrate_before, bounds.validate_before - 1],
        "label_cutoffs": [
            bounds.train_before - 1,
            bounds.calibrate_before - 1,
            bounds.snapshot - 1,
        ],
        "fold_start": [
            bounds.train_before,
            bounds.calibrate_before,
            bounds.validate_before,
        ],
        "calibration_points": len(steps),
        "interval_radius": radius,
    }
    gate = (
        passed
        and model.state is not None
        and len(calibration) >= 16
        and overall["observed_support"] >= 16
    )
    return Assessment(steps, radius, gate, report, tuple(fragile))


def score_card(model, assessment, signal):
    estimate = apply_calibration(score(model, signal), assessment.calibration)
    prior = score(model, signal, baseline=True)
    lower = (
        max(0.0, estimate - assessment.radius)
        if assessment.radius is not None
        else None
    )
    upper = estimate + assessment.radius if assessment.radius is not None else None
    return ScoreCard(signal, estimate, prior, lower, upper)
