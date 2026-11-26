from dataclasses import replace

from lightbooking.shoot_holdout.contracts import Paired
from lightbooking.shoot_holdout.evaluation import (
    apply_calibration,
    censored_order,
    evaluate,
    paired_auc,
    percentile,
)
from lightbooking.shoot_holdout.service import backcheck, paired, score_card
from lightbooking.settings import TARGET


def test_holdout_separates_ordered_periods(learning):
    # TRAP-43
    intake, fold, _, signals, _, model = learning
    calibration = paired(
        signals,
        intake,
        fold.train_before,
        fold.calibrate_before,
        fold.calibrate_before - 1,
        model,
    )
    replay = paired(
        signals,
        intake,
        fold.calibrate_before,
        fold.validate_before,
        fold.snapshot - 1,
        model,
    )
    groups = [
        set(model.training_cases),
        {r.case_id for r in calibration},
        {r.case_id for r in replay},
    ]
    assert all(groups) and not any(
        a & b for idx, a in enumerate(groups) for b in groups[idx + 1 :]
    )
    assert len(replay) > 32


def test_paired_summary_and_group_totals_agree(learning):
    intake, fold, _, signals, _, model = learning
    report = backcheck(signals, intake, fold, model).report
    assert (
        sum(bucket["support"] for bucket in report["groups"].values())
        == report["holdout_cases"]
    )
    assert report["overall"]["support"] == report["holdout_cases"]
    assert report["calibration_cases"] >= 16
    assert (
        report["label_cutoffs"][0]
        < report["label_cutoffs"][1]
        < report["label_cutoffs"][2]
    )


def test_auc_treats_equal_estimates_as_half_credit():
    rows = [Paired("a", "g", 0, 0.5, 0.8, True), Paired("b", "g", 1, 0.5, 0.3, True)]
    assert paired_auc(rows) == 0.5
    assert paired_auc(rows, baseline=True) == 0.0
    assert paired_auc(rows[:1]) is None


def test_censor_before_observed_event_is_not_comparable():
    rows = [
        Paired("A", "g", 8, 4, 5, True),
        Paired("B", "g", 5, 8, 6, False),
        Paired("C", "g", 11, 8, 5, False),
    ]
    assert censored_order(rows) == 1.0
    assert censored_order(rows, baseline=True) == 0.5
    assert censored_order(rows[:2]) is None


def test_coverage_requires_actual_observation():
    with_censor = [Paired("A", "g", 9, 9, 4, True), Paired("B", "g", 20, 0, 6, False)]
    assert evaluate(with_censor, 1)["interval_coverage"] == 1
    no_data = evaluate([], 1)
    assert no_data["loss"] is None and no_data["observed_support"] == 0


def test_score_intervals_match_calibration_kind(learning):
    intake, fold, _, signals, _, model = learning
    check = backcheck(signals, intake, fold, model)
    forecast = score_card(model, check, signals[-1])
    if TARGET in {"binary", "anomaly"}:
        assert forecast.lower is None and 0 <= forecast.estimate <= 1
        assert apply_calibration(0.44, ()) == 0.44
    else:
        assert 0 <= forecast.lower <= forecast.estimate <= forecast.upper


def test_replay_thin_is_explicit(learning):
    intake, fold, _, signals, _, model = learning
    check = backcheck(signals[:7], intake, fold, model)
    assert not check.test_passed
    assert check.report["overall"]["loss"] is None
    assert percentile([], 0.8) is None
