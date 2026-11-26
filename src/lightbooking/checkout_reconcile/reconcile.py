from collections import Counter
from dataclasses import asdict
import csv
from hashlib import sha256
import io
import json
from math import isfinite

from .contracts import AccountingError


VALID_STATUS = frozenset({"allocated", "deferred", "held", "manual", "monitor"})


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def verify(plan):
    allocated = [entry for entry in plan.decisions if entry.status == "allocated"]
    actual = Counter()
    ids = set()
    for entry in plan.decisions:
        if entry.case_id in ids:
            raise AccountingError("一笔单据被分派两次")
        if entry.status not in VALID_STATUS:
            raise AccountingError("存在尚未归类的单据")
        if entry.units < 1 or not isfinite(entry.estimate):
            raise AccountingError("资源需求或估计结果异常")
        ids.add(entry.case_id)
    for entry in allocated:
        if entry.source != "trained":
            raise AccountingError("人工复核或回退单据不能占用自动分派额度")
        actual[entry.resource] += entry.units
    if (
        dict(actual) != plan.resource_use
        or sum(actual.values()) != plan.used
        or plan.used > plan.capacity
    ):
        raise AccountingError("分派资源余量与逐单明细对不上")


def export_table(body):
    rows = io.StringIO(newline="")
    columns = (
        "case_id",
        "cohort",
        "calendar_day",
        "tick",
        "estimate",
        "priority",
        "units",
        "status",
        "reason",
        "source",
        "next_step",
    )
    writer = csv.DictWriter(rows, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(body["decisions"])
    return rows.getvalue()


def counts(plan):
    by_state = Counter(item.status for item in plan.decisions)
    by_cause = Counter(item.reason for item in plan.decisions)
    cohort = Counter(item.cohort for item in plan.decisions)
    return dict(by_state), dict(by_cause), dict(cohort)


def compare_records(current, earlier):
    first = {item["case_id"]: item for item in earlier["decisions"]}
    second = {item["case_id"]: item for item in current["decisions"]}
    changes = []
    for case_id in sorted(first.keys() | second.keys()):
        left, right = first.get(case_id), second.get(case_id)
        if (
            left is None
            or right is None
            or (left["status"], left["reason"]) != (right["status"], right["reason"])
        ):
            changes.append(
                {
                    "case_id": case_id,
                    "before": left["status"] if left else None,
                    "after": right["status"] if right else None,
                    "reason": right["reason"] if right else "OUTSIDE_SCOPE",
                }
            )
    return changes
