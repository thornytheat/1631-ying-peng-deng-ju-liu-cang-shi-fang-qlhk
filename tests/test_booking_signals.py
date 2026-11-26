from dataclasses import replace
from math import isfinite

from lightbooking.lighting_holds.service import stage
from lightbooking.booking_signals.domain import robust_scale
from lightbooking.booking_signals.service import encode, learn_bank, ranges, trace
from lightbooking.settings import FIELD_BOUNDS, SIGNAL_NAMES


def test_zero_variance_uses_unit_scale():
    # TRAP-32
    assert robust_scale([1e8] * 9) == (1e8, 1.0)
    assert robust_scale([1e8 - 1, 1e8, 1e8 + 1]) == (1e8, 1.4826)


def test_future_and_late_measurements_do_not_fit(observation):
    # TRAP-42
    late = {**observation, "case_id": "QA-LATE", "arrived": 23}
    future = {**observation, "case_id": "QA-NEXT", "day": 24, "arrived": 24}
    book = stage({"observations": [observation, late, future], "outcomes": []}, 50)
    result = learn_bank(book.observations, 23)
    assert result.global_scale.support == 1
    assert result.population[observation["group"]] == 1


def test_missing_value_and_real_zero_have_different_evidence(learning):
    _, _, bank, signals, _, _ = learning
    record = signals[0].record
    field = next(iter(FIELD_BOUNDS))
    changed = encode(replace(record, reported={**record.reported, field: None}), bank)
    assert field in changed.missing
    assert trace(changed)["measurements"][field] is None
    assert all(isfinite(value) for value in changed.vector)
    complete = encode(
        replace(record, reported={**record.reported, field: FIELD_BOUNDS[field][0]}),
        bank,
    )
    assert field not in complete.missing


def test_low_group_coverage_uses_global_bank(learning):
    _, _, _, signals, _, _ = learning
    rows = tuple(entry.record for entry in signals[:4])
    fitted = learn_bank(rows, 70)
    assert not fitted.group_scales
    assert encode(rows[-1], fitted).reference == "全域"
    assert sum(fitted.population.values()) == len(rows)


def test_feature_trace_orders_training_quantities(learning):
    _, _, _, signals, _, _ = learning
    result = trace(signals[0])
    assert list(result["features"]) == list(SIGNAL_NAMES)
    assert list(result["standardized"]) == list(SIGNAL_NAMES)
    assert max(abs(value) for value in result["standardized"].values()) <= 12


def test_range_evidence_tracks_observed_minimum_and_maximum(learning):
    _, _, _, signals, _, _ = learning
    summary = ranges(signals)
    for i, name in enumerate(SIGNAL_NAMES):
        seen = [row.vector[i] for row in signals]
        assert (summary[name]["min"], summary[name]["max"]) == (min(seen), max(seen))
        assert summary[name]["min"] <= summary[name]["median"] <= summary[name]["max"]


def test_header_only_history_produces_sane_defaults(learning):
    _, _, _, signals, _, _ = learning
    blank = learn_bank((), 100)
    assert blank.global_scale.support == 0 and not blank.group_scales
    assert all(isfinite(n) for n in encode(signals[0].record, blank).normalized)
