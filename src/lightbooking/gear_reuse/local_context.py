from collections import Counter
from statistics import median


def _fixture_availability(row):
    entry = row.record.reported
    qs = (entry["replacement"], entry["units"], entry["signed"])
    if None in qs:
        return None
    return (
        (entry["replacement"] - entry["units"])
        if not entry["signed"]
        else -entry["units"]
    )


def context(current, neighbors, old, score):
    hold = current.record.reported
    by_slot = Counter()
    for scheduled in neighbors:
        arrival = scheduled.record.reported
        if (
            arrival["signed"] == 1
            and scheduled.record.case_id != current.record.case_id
        ):
            if 0 <= scheduled.record.day - current.record.day <= 2:
                by_slot[scheduled.record.clock // 8] += arrival["units"] or 0
    previous = [
        balance for row in old if (balance := _fixture_availability(row)) is not None
    ]
    current_slot = by_slot[current.record.clock // 8]
    current_balance = _fixture_availability(current)
    fragile = (
        current_balance is not None
        and current_balance < 0
        and current_slot > 8
        and (hold["lead_hr"] or 0) < 24
    )
    return {
        "decision": "同窗已签预约占用替代套件" if fragile else "",
        "support": len(previous),
        "committed_units": current_slot,
        "spare_kit_balance": current_balance,
        "ordinary_fixture_level": median(previous) if previous else None,
        "cancel_expected_units": score * (hold["units"] or 0),
    }
