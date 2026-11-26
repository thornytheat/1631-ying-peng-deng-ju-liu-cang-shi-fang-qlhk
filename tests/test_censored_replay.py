"""提前撤仓单据的回放处置：未知结局成对计分、整组最不利核验、精确临界裁决。"""

from copy import deepcopy
from fractions import Fraction

from lightbooking.engine import plan
from lightbooking.lighting_holds.service import known_labels, stage
from lightbooking.booking_signals.service import encode, learn_bank
from lightbooking.rental_hist_bayes.service import fit
from lightbooking.shoot_holdout.contracts import Paired
from lightbooking.shoot_holdout.evaluation import (
    TOLERANCE_INTERCEPT,
    exceeds_allowance,
    margin_term,
    observed_margin,
    worst_case_margin,
)
from lightbooking.shoot_holdout.service import backcheck, paired, split
from lightbooking.settings import DEFAULT_DAY, GROUPS


def replay_window_ids(packet, group=None):
    bounds = split(DEFAULT_DAY)
    return {
        row["case_id"]
        for row in packet["observations"]
        if bounds.calibrate_before <= row["day"] < bounds.validate_before
        and (group is None or row["group"] == group)
    }


def test_unreceipted_orders_stay_out_of_training_and_calibration(learning):
    # 撤仓前没收到结案回执的单不参与训练和校准
    intake, fold, _, signals, _, model = learning
    train_labels = known_labels(intake, fold.train_before - 1)
    train_window = {
        row.record.case_id
        for row in signals
        if row.record.day < fold.train_before
        and row.record.arrived <= fold.train_before - 1
    }
    assert train_window - set(train_labels)
    assert set(model.training_cases) <= set(train_labels)

    calibration_labels = known_labels(intake, fold.calibrate_before - 1)
    calibration_window = {
        row.record.case_id
        for row in signals
        if fold.train_before <= row.record.day < fold.calibrate_before
        and row.record.arrived <= fold.calibrate_before - 1
    }
    assert calibration_window - set(calibration_labels)
    calibration = paired(
        signals,
        intake,
        fold.train_before,
        fold.calibrate_before,
        fold.calibrate_before - 1,
        model,
    )
    assert {row.case_id for row in calibration} <= set(calibration_labels)


def test_replay_cohort_marks_withdrawn_order_as_unknown_outcome(original):
    # 回放段内撤仓的单据进入回放队列，但标记为结局未知
    packet = deepcopy(original)
    withdrawn = next(iter(replay_window_ids(packet)))
    packet["outcomes"] = [
        row for row in packet["outcomes"] if row["case_id"] != withdrawn
    ]
    intake = stage(packet, DEFAULT_DAY)
    bounds = split(DEFAULT_DAY)
    snapshot = stage(packet, bounds.train_before - 1)
    bank = learn_bank(snapshot.observations, bounds.train_before)
    signals = [encode(row, bank) for row in intake.observations]
    history = [encode(row, bank) for row in snapshot.observations]
    model = fit(history, known_labels(snapshot, bounds.train_before - 1))

    labeled_only = paired(
        signals, intake, bounds.calibrate_before, bounds.validate_before,
        bounds.snapshot - 1, model,
    )
    assert withdrawn not in {row.case_id for row in labeled_only}

    cohort = paired(
        signals, intake, bounds.calibrate_before, bounds.validate_before,
        bounds.snapshot - 1, model, include_unknown=True,
    )
    row = next(item for item in cohort if item.case_id == withdrawn)
    assert not row.occurred and row.actual < 0
    assert len(cohort) == len(labeled_only) + 1


def test_worst_case_scores_both_estimators_against_the_same_outcome():
    # 同一笔未知结局，新旧估法按同一结果算，取让新估法最吃亏的结局
    row = Paired("W", "g", -1.0, 0.9, 0.1, False)
    at_zero = margin_term(0.9, 0.1, 0.0)
    at_one = margin_term(0.9, 0.1, 1.0)
    assert at_zero > 0 > at_one
    assert worst_case_margin([row]) == max(at_zero, at_one)
    known = Paired("K", "g", 1.0, 0.9, 0.1, True)
    assert worst_case_margin([known]) == margin_term(0.9, 0.1, 1.0)
    assert observed_margin([row, known]) == margin_term(0.9, 0.1, 1.0)


def test_critical_line_is_exact_and_not_swayed_by_rounding():
    # 临界分数：恰好压在容许线上不算越线，浮点舍入不能左右裁决
    count = 20
    line = TOLERANCE_INTERCEPT * count
    assert not exceeds_allowance(line, count)
    assert exceeds_allowance(line + Fraction(1, 10**18), count)
    assert not exceeds_allowance(line - Fraction(1, 10**18), count)
    # 0.1+0.1+0.1 在浮点下会越过 0.015×20，精确分数恰好压线
    margin = sum(Fraction(1, 10) for _ in range(3))
    assert margin == line
    assert not exceeds_allowance(margin, count)
    assert 0.1 + 0.1 + 0.1 > 0.015 * 20


def test_fragile_group_goes_manual_and_releases_no_seats(packet, report):
    # 任一可能结局组合下越线的棚组整组转人工，不占席位
    withdrawn = replay_window_ids(packet, GROUPS[0])
    assert withdrawn
    packet["outcomes"] = [
        row for row in packet["outcomes"] if row["case_id"] not in withdrawn
    ]
    result = plan(packet).body
    assert result["evaluation_passed"]
    assert result["evaluation"]["fragile_groups"] == [GROUPS[0]]
    group_report = result["evaluation"]["groups"][GROUPS[0]]
    assert group_report["censored"] == len(withdrawn)
    assert group_report["worst_case_exceeds"]

    baseline = {row["case_id"]: row for row in report.body["decisions"]}
    for row in result["decisions"]:
        if row["cohort"] != GROUPS[0]:
            continue
        if baseline[row["case_id"]]["reason"] == "BUSINESS_LOCK":
            # 合同和套件限制照旧
            assert row["status"] == "held" and row["reason"] == "BUSINESS_LOCK"
        else:
            assert row["status"] == "manual"
            assert "REPLAY_WORST_CASE" in row["details"]
    assert all(
        row["cohort"] != GROUPS[0]
        for row in result["decisions"]
        if row["status"] == "allocated"
    )
    assert result["summary"]["used"] <= result["summary"]["capacity"]


def test_group_with_confirmed_receipts_is_not_flagged(report):
    # 档案回放段回执齐全，没有任何一组被判越线
    evaluation = report.body["evaluation"]
    assert evaluation["fragile_groups"] == []
    assert all(
        not group["worst_case_exceeds"] for group in evaluation["groups"].values()
    )
    assert evaluation["overall"]["observed_support"] == evaluation["holdout_cases"]


def test_late_withdrawal_record_past_replay_deadline_keeps_roster(packet, report):
    # 晚到的撤仓记录过了回放截止日：重算也不改当班名单
    bounds = split(DEFAULT_DAY)
    target = next(iter(replay_window_ids(packet)))
    packet["outcomes"] = [
        row for row in packet["outcomes"] if row["case_id"] != target
    ]
    without_receipt = plan(packet).body
    late = deepcopy(packet)
    # 回执在快照日内可见，但晚于回放标签截止日
    assert bounds.snapshot - 1 < DEFAULT_DAY
    late["outcomes"].append(
        {
            "case_id": target,
            "available": DEFAULT_DAY,
            "value": 1,
            "occurred": True,
        }
    )
    with_late_receipt = plan(late).body
    assert with_late_receipt["decisions"] == without_receipt["decisions"]
    assert with_late_receipt["schedule"] == without_receipt["schedule"]
    assert (
        with_late_receipt["evaluation"]["holdout_cases"]
        == without_receipt["evaluation"]["holdout_cases"]
    )


def test_overall_gate_uses_exact_margin_on_sample_archive(learning):
    intake, fold, _, signals, _, model = learning
    check = backcheck(signals, intake, fold, model)
    assert check.test_passed
    assert check.fragile_groups == ()
    assert check.report["fragile_groups"] == []
    # 报告逐组给出最不利余量供复核
    assert all(
        "worst_case_margin" in group for group in check.report["groups"].values()
    )
