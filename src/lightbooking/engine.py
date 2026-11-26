from pathlib import Path

from .lighting_holds.service import known_labels, sample, stage
from .booking_signals.service import (
    encode,
    fit_audit,
    learn_bank,
    measure_sensitivity,
    ranges,
    reference_summary,
    trace,
)
from .rental_hist_bayes.service import fit, forecast_card
from .shoot_holdout.service import backcheck, score_card, split
from .client_mix.service import decide, readiness, review, shift_alerts
from .gear_reuse.service import (
    allocate,
    context,
    operational_check,
    quota,
    review_capacity,
    summarize_workload,
)
from .checkout_reconcile.service import compile_delivery
from .settings import DEFAULT_BUDGET, DEFAULT_DAY, FIELD_BOUNDS, CRITICAL_FIELDS
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[2]


def plan(packet=None, *, as_of=DEFAULT_DAY, capacity=DEFAULT_BUDGET):
    if type(as_of) is not int or not 70 <= as_of <= 36_500:
        raise ValueError("快照日上午必须在第 70 日至第 36500 日之间")
    capacity = quota(capacity)
    packet = sample(ROOT) if packet is None else packet
    intake = stage(packet, as_of)
    bounds = split(as_of)
    training_snapshot = stage(packet, bounds.train_before - 1)
    bank = learn_bank(training_snapshot.observations, bounds.train_before)
    signals = [encode(row, bank) for row in intake.observations]
    history = [encode(row, bank) for row in training_snapshot.observations]
    model = fit(history, known_labels(training_snapshot, bounds.train_before - 1))
    assessment = backcheck(signals, intake, bounds, model)
    # 候选只用在快照日已入账的单据，候选结果标签不参与得分。
    ready = [
        item for item in signals if bounds.validate_before <= item.record.day <= as_of
    ]
    shifts = review(history, ready)
    current_groups = {}
    historic_groups = {}
    for row in ready:
        current_groups.setdefault(row.record.group, []).append(row)
    for row in history:
        historic_groups.setdefault(row.record.group, []).append(row)
    decisions = []
    details = {}
    for signal in ready:
        rules = decide(
            signal,
            shifts,
            assessment.test_passed,
            history,
            assessment.fragile_groups,
        )
        estimate = score_card(model, assessment, signal)
        fields = signal.record.reported
        filled = {
            key: (max(lo, 0.0) if key in CRITICAL_FIELDS else (lo + hi) / 2)
            if fields.get(key) is None
            else fields[key]
            for key, (lo, hi) in FIELD_BOUNDS.items()
        }
        operative_score = estimate.estimate if rules.allowed else estimate.prior
        operating = operational_check(filled, operative_score)
        local = context(
            signal,
            current_groups[signal.record.group],
            historic_groups.get(signal.record.group, []),
            operative_score,
        )
        if rules.allowed and (operating["requires_operator"] or local["decision"]):
            reasons = tuple(
                note for note in (operating["reason"], local["decision"]) if note
            )
            rules = replace(rules, allowed=False, reasons=reasons, source="incumbent")
        decisions.append((estimate, rules))
        details[signal.record.case_id] = {
            **trace(signal),
            "trained_estimate": estimate.estimate,
            "incumbent_estimate": estimate.prior,
            "trust_reasons": list(rules.reasons),
            "used_source": rules.source,
            "operational_check": operating,
            "operating_context": local,
            "sensitivity": measure_sensitivity(signal, bank, ("units", "replacement")),
        }
    result = allocate(decisions, capacity, as_of)
    return compile_delivery(
        snapshot=as_of,
        plan=result,
        intake=intake,
        assessment=assessment,
        drift=shifts,
        model=forecast_card(model, ready, bank),
        signals={
            "ranges": ranges(ready),
            "reference_coverage": fit_audit(ready, bank),
            "reference_scale": reference_summary(bank),
            "shift_alerts": shift_alerts(shifts),
            "shift_coverage": readiness(shifts),
            "workload_review": summarize_workload(result.decisions, details),
            "capacity_review": review_capacity(result),
        },
        details=details,
    )
