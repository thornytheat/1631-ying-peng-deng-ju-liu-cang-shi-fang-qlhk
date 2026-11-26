from dataclasses import replace
from math import isfinite, log, sqrt
from statistics import median

import pytest

from lightbooking.booking_signals.service import encode
from lightbooking.rental_hist_bayes.service import score
from lightbooking.shoot_holdout.service import backcheck, paired, score_card
from lightbooking.gear_reuse.service import context
from lightbooking.settings import FIELD_BOUNDS, TARGET


def test_estimators_reject_unchanged_point_baseline_on_real_holdout(learning):
    book, bounds, _, signals, _, model = learning
    result = backcheck(signals, book, bounds, model)
    stats = result.report["overall"]
    assert result.test_passed
    assert stats["support"] >= 70
    assert stats["observed_support"] <= stats["support"]
    assert stats["reference_loss"] >= 0 and stats["loss"] >= 0
    if TARGET == "anomaly":
        assert stats["auc"] >= 0.48
    else:
        assert stats["loss"] <= 1.25 * stats["reference_loss"] + 0.015
    if stats.get("auc") is not None:
        assert 0 <= stats["auc"] <= 1
    if stats.get("concordance") is not None:
        assert 0 <= stats["concordance"] <= 1


def test_manual_reference_metric_matches_report(learning):
    book, bounds, _, signals, _, model = learning
    replay = paired(
        signals,
        book,
        bounds.calibrate_before,
        bounds.validate_before,
        bounds.snapshot - 1,
        model,
    )
    observed = [(row.actual, row.incumbent) for row in replay if row.occurred]
    if TARGET in {"binary", "anomaly"}:
        computed = sum((actual - prior) ** 2 for actual, prior in observed) / len(
            observed
        )
    elif TARGET == "count":

        def deviance(actual, prior):
            mean = max(prior, 1e-7)
            log_ratio = log(actual / mean) if actual else 0
            return 2 * (actual * log_ratio - actual + mean)

        computed = sum(deviance(actual, prior) for actual, prior in observed) / len(
            observed
        )
    else:
        computed = sum(abs(actual - prior) for actual, prior in observed) / len(
            observed
        )
    assert backcheck(signals, book, bounds, model).report["overall"][
        "reference_loss"
    ] == pytest.approx(computed)


def test_realistic_input_endpoints_remain_finite_through_inference(learning):
    _, _, bank, signals, _, model = learning
    current = signals[-1].record
    for position in range(2):
        values = {key: bounds[position] for key, bounds in FIELD_BOUNDS.items()}
        encoded = encode(replace(current, reported=values), bank)
        prediction = score(model, encoded)
        assert prediction >= 0 and isfinite(prediction)
        if TARGET in {"binary", "anomaly"}:
            assert prediction <= 1


def test_null_operating_context_is_total_on_incomplete_reference(learning):
    _, _, bank, signals, _, model = learning
    current = signals[-1].record
    empty = replace(current, reported={key: None for key in FIELD_BOUNDS})
    row = encode(empty, bank)
    evidence = context(row, [row], [row], score(model, row))
    assert evidence["support"] >= 0
    assert isinstance(evidence["decision"], str)
    assert evidence["support"] <= 1


def test_covariate_lengths_survive_batch_and_release_projection(report, learning):
    book, bounds, _, signals, _, model = learning
    assessment = backcheck(signals, book, bounds, model)
    by_id = {row.record.case_id: row for row in signals}
    for entry in report.body["decisions"]:
        computed = score_card(model, assessment, by_id[entry["case_id"]])
        evidence = report.body["row_evidence"][entry["case_id"]]
        assert len(evidence["features"]) == len(evidence["standardized"]) == 4
        assert evidence["incumbent_estimate"] == pytest.approx(computed.prior)
        if entry["source"] == "trained":
            assert entry["estimate"] == pytest.approx(computed.estimate, abs=0.000001)
        else:
            assert entry["estimate"] == pytest.approx(computed.prior, abs=0.000001)
        if computed.lower is not None:
            assert computed.lower <= computed.estimate <= computed.upper
        if entry["status"] == "allocated":
            assert not evidence["trust_reasons"]
