from collections import defaultdict

from ..settings import CRITICAL_FIELDS, GROUPS, WATCH_FEATURE
from .diagnostics import readiness, shift_alerts
from .contracts import Check, DriftReport, Gate
from .population import compare, extreme_signal, missing_rate


def review(reference, candidates):
    history = defaultdict(list)
    live = defaultdict(list)
    for row in reference:
        history[row.record.group].append(row)
    for row in candidates:
        live[row.record.group].append(row)
    checks = {}
    for group in GROUPS:
        old, new = history[group], live[group]
        columns = compare(old, new)
        winner = (
            max(columns, key=lambda name: columns[name]["psi"] or 0)
            if old and new
            else None
        )
        peak = columns[winner]["psi"] if winner else None
        missing = max(0.0, missing_rate(new) - missing_rate(old))
        extremes = {
            key: stats["outside"]
            for key, stats in columns.items()
            if stats["outside"] is not None
        }
        watched = columns[WATCH_FEATURE]
        if not new:
            status = "NO_BATCH"
        elif len(old) < 14 or len(new) < 5:
            status = "LOW_SUPPORT"
        elif (
            (peak is not None and peak > 1.02)
            or missing > 0.42
            or max(extremes.values(), default=0) > 0.48
        ):
            status = "REGIME_CHANGED"
        elif watched["psi"] is not None and watched["psi"] > 0.55:
            status = "WATCH"
        else:
            status = "STABLE"
        checks[group] = Check(
            group, status, len(old), len(new), winner, peak, missing, extremes, columns
        )
    return DriftReport(
        checks,
        len(candidates),
        sum(
            c.live
            for c in checks.values()
            if c.status in {"LOW_SUPPORT", "REGIME_CHANGED"}
        ),
    )


def decide(signal, report, assessment_passed, reference):
    notes = []
    if set(signal.missing) & CRITICAL_FIELDS:
        notes.append("MISSING_DECISION_FIELD")
    if not assessment_passed:
        notes.append("BACKTEST_GATE")
    cohort = report.groups[signal.record.group]
    if cohort.status in {"LOW_SUPPORT", "REGIME_CHANGED"}:
        notes.append(cohort.status)
    local = [entry for entry in reference if entry.record.group == signal.record.group]
    if len(local) >= 14 and extreme_signal(signal, local):
        notes.append("OUT_OF_REFERENCE")
    return Gate(not notes, tuple(notes), "incumbent" if notes else "trained")
