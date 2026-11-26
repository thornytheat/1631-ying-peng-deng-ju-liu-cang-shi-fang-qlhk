from dataclasses import replace

import pytest

from lightbooking.gear_reuse.contracts import Request
from lightbooking.gear_reuse.domain import resource_limit
from lightbooking.gear_reuse.service import allocate_requests


def case(case_id="A", cohort="one", priority=8.0, unit=1, slot=37, status="candidate"):
    source = "incumbent" if status == "manual" else "trained"
    return Request(
        case_id,
        cohort,
        12,
        slot,
        cohort,
        unit,
        priority,
        None,
        None,
        priority,
        source,
        status,
        "BASE",
        (),
        "待复核",
    )


def test_prohibited_entries_never_spend():
    # TRAP-19
    prohibited = [
        case("C", status="manual"),
        case("B", status="held"),
        case("D", status="monitor"),
    ]
    attempt = allocate_requests([*prohibited, case("A")], 15)
    assert attempt.used == 1
    assert [row.case_id for row in attempt.decisions if row.status == "allocated"] == [
        "A"
    ]
    assert {r.status for r in attempt.decisions if r.case_id != "A"} == {
        "manual",
        "held",
        "monitor",
    }


def test_quota_cannot_fragment_one_case():
    batch = allocate_requests([case("A", unit=3), case("B", unit=2)], 1)
    assert batch.used == 0 and len(batch.decisions) == 2
    assert {r.units for r in batch.decisions} == {2, 3}
    assert all(row.status == "deferred" for row in batch.decisions)


def test_resource_caps_bound_even_when_total_remains():
    cases = [case(str(i), slot=2 * i) for i in range(20)]
    batch = allocate_requests(cases, 20)
    assert batch.resource_use.get("one", 0) == resource_limit(20)
    assert batch.used < batch.capacity


def test_invalid_quota_and_duplicate_case_are_rejected():
    for capacity in (-1, 101, 3.1, True):
        with pytest.raises(ValueError, match="额度"):
            allocate_requests([], capacity)
    with pytest.raises(ValueError, match="重复"):
        allocate_requests([case(), case(priority=0.3)], 9)


def test_equal_priorities_produce_same_plan_in_any_order():
    listings = [
        case("E", slot=55),
        case("A", slot=55),
        case("C", cohort="two", slot=55),
    ]
    assert allocate_requests(listings, 12) == allocate_requests(listings[::-1], 12)


def test_seeded_default_respects_all_resource_limits(report):
    body = report.body
    assert body["summary"]["proposed"] > 0
    assert sum(body["resource"].values()) == body["summary"]["used"]
    assert all(
        c <= resource_limit(body["summary"]["capacity"])
        for c in body["resource"].values()
    )
    permitted = {r["case_id"] for r in body["decisions"] if r["status"] == "allocated"}
    assert all(not body["row_evidence"][key]["trust_reasons"] for key in permitted)


def test_zero_capacity_preserves_existing_hard_lock():
    items = [case("A"), case("B", status="held")]
    batch = allocate_requests(items, 0)
    assert batch.used == 0
    assert [(row.case_id, row.status) for row in batch.decisions] == [
        ("A", "deferred"),
        ("B", "held"),
    ]
