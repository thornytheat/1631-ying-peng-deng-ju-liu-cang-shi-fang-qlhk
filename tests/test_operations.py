from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import permutations
from math import isfinite
from statistics import median

import pytest

from lightbooking.booking_signals.service import (
    fit_audit,
    measure_sensitivity,
    reference_summary,
)
from lightbooking.rental_hist_bayes.service import forecast_card, score
from lightbooking.client_mix.service import readiness, review, shift_alerts
from lightbooking.gear_reuse.service import operational_check
from lightbooking.hold_registry.history import release_changes
from lightbooking.hold_registry.service import list_releases, register
from lightbooking.engine import plan
from lightbooking.settings import DEFAULT_DAY, FIELD_BOUNDS, GROUPS, TARGET


def raw_midpoints():
    return {field: (lo + hi) / 2 for field, (lo, hi) in FIELD_BOUNDS.items()}


def test_operating_range_has_finite_impact_and_named_headroom():
    low = {field: bounds[0] for field, bounds in FIELD_BOUNDS.items()}
    high = {field: bounds[1] for field, bounds in FIELD_BOUNDS.items()}
    left = operational_check(low, 0.28)
    right = operational_check(high, 0.8)
    assert left["name"] == right["name"] and left["headroom_label"]
    assert isinstance(left["requires_operator"], bool)
    assert isfinite(left["impact"]) and isfinite(right["headroom"])
    assert left["headroom"] != right["headroom"] or left["impact"] != right["impact"]


def test_schedule_covers_each_allocated_ticket_once(report):
    schedule = report.body["schedule"]
    assigned = {
        row["case_id"]: row
        for row in report.body["decisions"]
        if row["status"] == "allocated"
    }
    days = set()
    total = 0
    ids = []
    for lane in schedule:
        running = 0
        for ticket in lane["tickets"]:
            matching = assigned[ticket["id"]]
            ids.append(ticket["id"])
            days.add(matching["calendar_day"])
            running += matching["units"]
            assert ticket["running_units"] == running
            assert ticket["window_end"] - ticket["window_start"] == matching["units"]
            assert ticket["instruction"] == report.body["action"]
        assert lane["units"] == running
        total += running
    assert len(ids) == len(set(ids)) == len(assigned)
    assert set(ids) == assigned.keys()
    assert total == report.consumed
    assert report.body["handover"]["assigned_days"] == sorted(days)
    assert all(day > report.as_of for day in days)


def test_handover_assigns_different_reason_and_work_for_each_queue(report):
    body = report.body
    handover = body["handover"]
    assert handover["schedule_rows"] == body["summary"]["proposed"]
    assert handover["blocked_by_business"] == body["summary"]["held"]
    assert handover["used_units"] == body["summary"]["used"]
    by_id = {row["case_id"]: row for row in body["decisions"]}
    priorities = [row["impact"] for row in handover["unserved_high_priority"]]
    assert priorities == sorted(priorities, reverse=True)
    for row in handover["unserved_high_priority"]:
        assert by_id[row["case_id"]]["status"] == "deferred"
        assert row["units_needed"] == by_id[row["case_id"]]["units"]


def test_workload_reconciles_business_exposure_by_group(report):
    body = report.body
    reviews = body["signal_ranges"]["workload_review"]
    for group, row in reviews.items():
        cohort = [claim for claim in body["decisions"] if claim["cohort"] == group]
        selected = [claim for claim in cohort if claim["status"] == "allocated"]
        review = [
            body["row_evidence"][claim["case_id"]]["operational_check"]
            for claim in cohort
        ]
        assert row["selected"] == len(selected)
        assert row["needs_operator"] == sum(
            item["requires_operator"] for item in review
        )
        expected = sum(
            body["row_evidence"][claim["case_id"]]["operational_check"]["impact"]
            for claim in selected
        )
        assert row["selected_impact"] == pytest.approx(expected, abs=0.0001)


def test_reference_card_uses_training_freeze_and_not_live_case_count(learning):
    _, fold, bank, signals, history, _ = learning
    live = [sig for sig in signals if sig.record.day >= fold.validate_before]
    reference = reference_summary(bank)
    records = fit_audit(live, bank)
    assert records["fitted_cases"] == len(history) == reference["sample_count"]
    assert records["reference_before"] == reference["cutoff"] == fold.train_before
    assert sum(records["used_references"].values()) == len(live)
    assert all(example > 0 for example in reference["scale"].values())
    assert sum(records["reference_groups"].values()) == reference["sample_count"]


def test_sensitivity_of_a_neutral_reading_is_zero(learning):
    _, _, bank, signals, _, _ = learning
    record = signals[0].record
    ref = bank.group_scales.get(record.group, bank.global_scale)
    neutral = replace(record, reported=dict(ref.fills))
    from lightbooking.booking_signals.service import encode

    result = measure_sensitivity(encode(neutral, bank), bank, tuple(FIELD_BOUNDS))
    assert len(result) == len(FIELD_BOUNDS)
    assert all(
        item["scaled_distance"] == 0
        and all(delta == 0 for delta in item["effect"].values())
        for item in result
    )


def test_review_readiness_distinguishes_coverage_from_drift(learning):
    _, _, _, signals, history, _ = learning
    batch = signals[-48:]
    check = review(history, batch)
    summary = readiness(check)
    assert summary["expected_groups"] == len(GROUPS)
    assert summary["populated_groups"] == len(GROUPS)
    assert summary["paired_candidates"] == len(batch)
    assert summary["reference_share"] == 1
    alerts = shift_alerts(check)
    assert [item["priority"] for item in alerts] == sorted(
        (item["priority"] for item in alerts), reverse=True
    )
    assert all(
        0 <= item["outside_share"] <= 1 and item["group"] in GROUPS for item in alerts
    )


def test_forecast_card_has_reproducible_scenario_and_sensible_summary(learning):
    _, _, bank, signals, _, model = learning
    models = forecast_card(model, signals[-5:], bank)
    distribution = models["forecast_summary"]
    expected = [score(model, signal) for signal in signals[-5:]]
    assert distribution["minimum"] == min(expected)
    assert distribution["maximum"] == max(expected)
    assert distribution["median"] == median(expected)
    assert models["stress"]["case_id"] == signals[-5].record.case_id
    assert len(models["stress"]["comparison"]) == 4
    assert all(isfinite(row["score_delta"]) for row in models["stress"]["comparison"])
    assert forecast_card(model, [], bank)["stress"] is None


def test_release_difference_preserves_parent_snapshot(tmp_path, report, original):
    store = tmp_path / "history.sqlite"
    first = register(store, report, 0)
    constrained = plan(original, capacity=0)
    second = register(store, constrained, 1)
    diff = release_changes(store, first.generation, second.generation)
    assert diff["run_ids"] == [report.digest, constrained.digest]
    assert diff["snapshot_days"] == [DEFAULT_DAY, DEFAULT_DAY]
    assert diff["resource_delta"]["used"] == -report.consumed
    assert diff["resource_delta"]["cases"] == 0
    assert diff["changed"] == sum(diff["transitions"].values())
    with pytest.raises(ValueError, match="早于"):
        release_changes(store, second.generation, first.generation)


def test_many_concurrent_retries_cannot_change_version(tmp_path, report):
    store = tmp_path / "replay.sqlite"
    original = register(store, report, 0)

    def attempt(_):
        return register(store, report, 0)

    with ThreadPoolExecutor(4) as pool:
        retries = list(pool.map(attempt, range(12)))
    assert {row.generation for row in retries} == {original.generation}
    assert set(row.run_id for row in retries) == {report.digest}
    assert all(row.replayed for row in retries)
    assert len(list_releases(store)) == 1


def test_future_outcome_cannot_change_current_decision(packet, report):
    selected = report.body["decisions"][0]
    case = selected["case_id"]
    packet["outcomes"].append(
        {"case_id": case, "available": DEFAULT_DAY + 2, "value": 1, "occurred": True}
    )
    result = plan(packet).body
    assert result["decisions"] == report.body["decisions"]
    assert result["model"] == report.body["model"]
    assert (
        result["intake"]["reasons"].get("LABEL_NOT_VISIBLE", 0)
        == report.body["intake"]["reasons"].get("LABEL_NOT_VISIBLE", 0) + 1
    )


def test_quota_alternatives_do_not_refit_or_change_trust(packet, report):
    baseline = report.body
    for quota in (0, 3, 70):
        alternative = plan(packet, capacity=quota).body
        assert alternative["model"] == baseline["model"]
        assert alternative["evaluation"] == baseline["evaluation"]
        assert alternative["row_evidence"] == baseline["row_evidence"]
        assert alternative["summary"]["used"] <= quota
        old = {
            row["case_id"]
            for row in baseline["decisions"]
            if row["status"] in {"manual", "held"}
        }
        new = {
            row["case_id"]
            for row in alternative["decisions"]
            if row["status"] in {"manual", "held"}
        }
        assert old == new


def test_peer_review_evidence_scoped_to_the_matching_group(report):
    rows = report.body["row_evidence"]
    found = [evidence["operating_context"] for evidence in rows.values()]
    assert all(item["support"] >= 0 for item in found)
    assert any(item["support"] > 0 for item in found)
    assert len({tuple(sorted(item)) for item in found if item["support"] > 0}) == 1
    for evidence in rows.values():
        review = evidence["operating_context"]
        if review["decision"] and review["decision"] in evidence["trust_reasons"]:
            assert evidence["used_source"] == "incumbent"
