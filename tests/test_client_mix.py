from dataclasses import replace

from lightbooking.client_mix.population import extreme_signal, histogram, index_shift
from lightbooking.client_mix.service import decide, review
from lightbooking.settings import CRITICAL_FIELDS, GROUPS, SIGNAL_NAMES


def test_constant_distribution_detects_outside():
    # TRAP-44
    compare = index_shift([5] * 30, [7] * 9)
    assert compare["psi"] == 0
    assert compare["outside"] == 1
    assert compare["current"] == [9]


def test_sparse_histogram_keeps_mass_even_at_edges():
    assert histogram([0.1, 0.25, 0.60, 0.60, 0.95], (0.25, 0.60, 0.95)) == [1, 1, 2, 1]
    shifted = index_shift([1, 2, 3, 4, 5] * 18, [3, 4, 7, 8, 9, 10])
    assert sum(shifted["reference"]) == 90 and sum(shifted["current"]) == 6
    assert shifted["psi"] > 0


def test_missing_distribution_means_no_batch(learning):
    *_, history, _ = learning
    checks = review(history, [])
    assert checks.assessed == 0 and checks.blocked == 0
    assert {check.status for check in checks.groups.values()} == {"NO_BATCH"}
    assert all(check.max_psi is None for check in checks.groups.values())


def test_individual_critical_missingness_blocks_even_stable_group(learning):
    *_, history, _ = learning
    group = GROUPS[0]
    peer = [row for row in history if row.record.group == group]
    ref = review(peer, peer)
    broken = replace(peer[-1], missing=(sorted(CRITICAL_FIELDS)[0],))
    verdict = decide(broken, ref, True, peer)
    assert not verdict.allowed and verdict.source == "incumbent"
    assert "MISSING_DECISION_FIELD" in verdict.reasons


def test_changed_feature_blocks_calculated_group(learning):
    *_, history, _ = learning
    peer = [row for row in history if row.record.group == GROUPS[0]]
    altered = [replace(row, vector=(999.0,) + row.vector[1:]) for row in peer[:15]]
    found = review(peer, altered)
    assert found.groups[GROUPS[0]].status == "REGIME_CHANGED"
    assert found.blocked == len(altered)
    assert SIGNAL_NAMES[0] in extreme_signal(altered[0], peer)


def test_one_row_cannot_clear_drift_or_holdout_gate(learning):
    *_, history, _ = learning
    tiny = history[:1]
    report = review(history, tiny)
    reasons = decide(tiny[0], report, False, history).reasons
    assert {"LOW_SUPPORT", "BACKTEST_GATE"} <= set(reasons)
