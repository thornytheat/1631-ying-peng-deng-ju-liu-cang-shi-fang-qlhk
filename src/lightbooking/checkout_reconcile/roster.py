from collections import defaultdict
from itertools import accumulate
from math import fsum


def build_schedule(decisions):
    slots = defaultdict(list)
    for ticket in decisions:
        if ticket.status != "allocated":
            continue
        slots[ticket.calendar_day, ticket.resource].append(ticket)
    lanes = []
    for (day, resource), entries in sorted(slots.items()):
        group = sorted(entries, key=lambda row: (row.tick, row.case_id))
        totals = list(accumulate(row.units for row in group))
        instructions = [
            {
                "id": row.case_id,
                "window_start": row.tick,
                "window_end": row.tick + row.units,
                "resource_units": row.units,
                "running_units": cumulative,
                "instruction": row.next_step,
            }
            for row, cumulative in zip(group, totals)
        ]
        lanes.append(
            {
                "day": day,
                "resource": resource,
                "units": totals[-1],
                "tickets": instructions,
                "protected_value": round(fsum(row.priority for row in group), 6),
            }
        )
    return lanes


def worst_unserved(decisions, limit=6):
    leftovers = sorted(
        (row for row in decisions if row.status == "deferred"),
        key=lambda row: (-row.priority, row.case_id),
    )
    return [
        {
            "case_id": row.case_id,
            "reason": row.reason,
            "impact": row.priority,
            "units_needed": row.units,
            "resource": row.resource,
        }
        for row in leftovers[:limit]
    ]


def handover_notes(report, schedule):
    from collections import Counter

    lanes = Counter(row["resource"] for row in schedule)
    summary = report["summary"]
    roster_days = sorted({row["day"] for row in schedule})
    return {
        "assigned_days": roster_days,
        "assigned_groups": len(lanes),
        "schedule_rows": sum(len(row["tickets"]) for row in schedule),
        "used_units": sum(row["units"] for row in schedule),
        "manual_backlog": summary["manual"],
        "blocked_by_business": summary["held"],
        "unserved_high_priority": worst_unserved(report["plan"].decisions),
    }
