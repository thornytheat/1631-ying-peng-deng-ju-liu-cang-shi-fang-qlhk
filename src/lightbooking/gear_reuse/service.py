from collections import Counter
from dataclasses import replace

from .allocation import reservations
from .contracts import Allocation
from .domain import project_request, resource_limit
from .operations import operational_check, summarize_workload
from .local_context import context


MAX_QUOTA = 100


def quota(value: int) -> int:
    if type(value) is not int or not 0 <= value <= MAX_QUOTA:
        raise ValueError(f"分派额度必须是 0 至 {MAX_QUOTA} 的整数")
    return value


def allocate(pairs, capacity: int, snapshot=None) -> Allocation:
    return allocate_requests(
        [
            project_request(
                card,
                gate,
                snapshot + 1 + (card.signal.record.day - snapshot + 11) // 3
                if snapshot is not None
                else None,
            )
            for card, gate in pairs
        ],
        capacity,
    )


def allocate_requests(requests, capacity: int) -> Allocation:
    capacity = quota(capacity)
    if len({row.case_id for row in requests}) != len(requests):
        raise ValueError("分派队列存在重复单据")
    ordered = sorted(
        requests,
        key=lambda row: (
            -row.priority,
            -row.estimate,
            row.calendar_day,
            row.tick,
            row.case_id,
        ),
    )
    candidates = [row for row in ordered if row.status == "candidate"]
    issued, decisions = reservations(candidates, capacity, resource_limit(capacity))
    rows = []
    used = Counter()
    for row in ordered:
        if row.case_id in issued:
            used[row.resource] += row.units
            rows.append(replace(row, status="allocated", reason="CAPACITY_RESERVED"))
        elif row.status == "candidate":
            why = decisions.get(row.case_id, "QUOTA_REACHED")
            rows.append(replace(row, status="deferred", reason=why))
        else:
            rows.append(row)
    return Allocation(
        capacity, sum(used.values()), dict(sorted(used.items())), tuple(rows)
    )


def review_capacity(plan: Allocation):
    remaining = plan.capacity - plan.used
    lanes = {}
    for entry in plan.decisions:
        if entry.status == "deferred":
            previous = lanes.get(entry.resource)
            if previous is None or entry.priority > previous["priority"]:
                lanes[entry.resource] = {
                    "case_id": entry.case_id,
                    "reason": entry.reason,
                    "priority": entry.priority,
                    "additional_units": max(0, entry.units - remaining),
                }
    return {"uncommitted": remaining, "next_case_by_resource": lanes}
