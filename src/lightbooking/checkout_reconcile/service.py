from collections import Counter
from dataclasses import asdict

from ..settings import ACTION_LABEL, PROJECT_NAME, RESERVE_LABEL, SIGNAL_NAMES, UNIT
from .contracts import AccountingError, Delivery
from .reconcile import canonical, compare_records, counts, digest, export_table, verify
from .roster import build_schedule, handover_notes


def compile_delivery(
    *, snapshot, plan, intake, assessment, drift, model, signals, details
):
    verify(plan)
    states, causes, groups = counts(plan)
    counts_by_stream = Counter()
    for issue in intake.rejections:
        counts_by_stream[issue.code] += issue.occurrences
    if sum(states.values()) != len(plan.decisions) or set(details) != {
        row.case_id for row in plan.decisions
    }:
        raise AccountingError("业务候选、结果和证据明细数量不一致")
    body = {
        "project": PROJECT_NAME,
        "as_of": snapshot,
        "unit": UNIT,
        "action": ACTION_LABEL,
        "quota_label": RESERVE_LABEL,
        "feature_names": list(SIGNAL_NAMES),
        "summary": {
            "cases": len(plan.decisions),
            "proposed": states.get("allocated", 0),
            "manual": states.get("manual", 0),
            "deferred": states.get("deferred", 0),
            "held": states.get("held", 0),
            "used": plan.used,
            "capacity": plan.capacity,
            "available": plan.capacity - plan.used,
            "groups": groups,
            "states": states,
            "reasons": causes,
            "rejected": sum(counts_by_stream.values()),
            "trained": model["training_support"],
        },
        "resource": plan.resource_use,
        "intake": {
            "incoming": intake.source_counts,
            "picked": len(intake.observations),
            "labels": len(intake.outcomes),
            "reasons": dict(counts_by_stream),
            "exceptions": [asdict(issue) for issue in intake.rejections],
        },
        "model": model,
        "evaluation": assessment.report,
        "evaluation_passed": assessment.test_passed,
        "drift": {
            "checked": drift.assessed,
            "manual_required": drift.blocked,
            "groups": {key: asdict(value) for key, value in drift.groups.items()},
        },
        "signal_ranges": signals,
        "row_evidence": details,
        "decisions": [asdict(item) for item in plan.decisions],
    }
    schedule = build_schedule(plan.decisions)
    body["schedule"] = schedule
    body["handover"] = handover_notes(
        {"summary": body["summary"], "plan": plan}, schedule
    )
    checksum = digest(body)
    body["run_id"] = checksum
    return Delivery(checksum, snapshot, len(plan.decisions), plan.used, body)


def evidence(report: dict, step: str):
    return {
        "ingestion": report["intake"],
        "features": report["signal_ranges"],
        "model": report["model"],
        "replay": report["evaluation"],
        "shift": report["drift"],
        "resources": {"used": report["resource"], "summary": report["summary"]},
    }[step]
