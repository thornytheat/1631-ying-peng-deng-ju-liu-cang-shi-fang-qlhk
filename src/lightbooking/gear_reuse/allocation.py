from collections import Counter


def reservations(candidates, remaining, resource_cap):
    accepted = set()
    reasons = {}
    consumed = Counter()
    for row in candidates:
        if consumed[row.resource] + row.units > resource_cap and row.units <= remaining:
            reasons[row.case_id] = "RESOURCE_CEILING"
        elif row.units <= remaining:
            accepted.add(row.case_id)
            consumed[row.resource] += row.units
            remaining -= row.units
    return accepted, reasons
