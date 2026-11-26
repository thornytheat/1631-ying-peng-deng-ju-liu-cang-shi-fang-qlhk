from math import isfinite

import pytest

from lightbooking.lighting_holds.service import known_labels
from lightbooking.rental_hist_bayes.service import card, fit, score
from lightbooking.settings import TARGET


def test_score_is_batch_invariant(learning):
    # TRAP-54
    *_, signals, history, model = learning
    tail = signals[-29:]
    reference = {row.record.case_id: score(model, row) for row in tail}
    assert len(reference) > 20
    assert reference == {
        row.record.case_id: score(model, row) for row in reversed(tail)
    }
    assert reference[tail[13].record.case_id] == score(model, tail[13])


def test_fit_is_deterministic_under_input_permutation(learning):
    book, fold, _, signals, history, model = learning
    comparison = fit(list(reversed(history)), known_labels(book, fold.train_before - 1))
    assert comparison.training_cases == model.training_cases
    assert card(comparison) == card(model)
    assert card(model)["parameters"]
    assert len({round(score(model, row), 4) for row in signals[-60:]}) > 3


def test_small_training_cohort_routes_to_finite_reference(learning):
    book, fold, _, _, history, _ = learning
    thin = fit(history[:5], known_labels(book, fold.train_before - 1))
    assert thin.state is None and "NOT_ENOUGH_TRAINING" in thin.warnings
    assert score(thin, history[0]) == score(thin, history[0], baseline=True)
    assert isfinite(score(thin, history[0]))


def test_label_corrections_after_freeze_are_absent(learning):
    book, fold, _, _, history, model = learning
    known = known_labels(book, fold.train_before - 1)
    if TARGET not in {"anomaly"}:
        assert set(model.training_cases) == {
            s.record.case_id for s in history if s.record.case_id in known
        }
    else:
        assert set(model.training_cases) == {s.record.case_id for s in history}
    assert all(label.available < fold.train_before for label in known.values())


def test_native_predictions_respect_target_domain(learning):
    *_, signals, _, model = learning
    values = [score(model, row) for row in signals[-60:]]
    assert min(values) >= 0
    assert all(isfinite(value) for value in values)
    if TARGET in {"binary", "anomaly"}:
        assert max(values) <= 1


def test_reference_can_be_called_without_estimator_state(learning):
    *_, signals, _, model = learning
    row = signals[-1]
    prior = model.by_group.get(row.record.group, model.incumbent)
    assert score(model, row, baseline=True) == pytest.approx(prior, abs=1e-8)


def test_estimator_input_is_subset_of_eligible_signals(learning):
    book, fold, _, _, history, model = learning
    ids = {signal.record.case_id for signal in history}
    assert model.support >= 24
    assert set(model.training_cases) <= ids
    assert len(set(model.training_cases)) == model.support
