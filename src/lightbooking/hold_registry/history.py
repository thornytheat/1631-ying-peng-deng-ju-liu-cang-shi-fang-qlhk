from collections import Counter

from ..checkout_reconcile.service import compare_records
from .service import read_release


def release_changes(path, before, after):
    if before >= after:
        raise ValueError("对照版本须早于目标版本")
    original = read_release(path, before)
    revised = read_release(path, after)
    differences = compare_records(revised.evidence, original.evidence)
    transitions = Counter(
        f"{row['before'] or '新增'}→{row['after'] or '移除'}" for row in differences
    )
    old = original.evidence["summary"]
    new = revised.evidence["summary"]
    ledger = {
        field: new[field] - old[field]
        for field in ("cases", "proposed", "manual", "used", "capacity")
    }
    return {
        "before": before,
        "after": after,
        "snapshot_days": [original.as_of, revised.as_of],
        "run_ids": [original.run_id, revised.run_id],
        "changed": len(differences),
        "transitions": dict(transitions),
        "resource_delta": ledger,
        "changes": differences,
    }
