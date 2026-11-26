from dataclasses import replace
import csv
from io import StringIO

import pytest

from lightbooking.gear_reuse.contracts import Allocation, Request
from lightbooking.checkout_reconcile.contracts import AccountingError
from lightbooking.checkout_reconcile.service import (
    compare_records,
    evidence,
    export_table,
)
from lightbooking.checkout_reconcile.reconcile import digest, verify
from lightbooking.engine import plan


def test_report_is_permutation_invariant(packet, report):
    # TRAP-53
    packet["observations"].reverse()
    packet["outcomes"].reverse()
    assert plan(packet).digest == report.digest


def test_report_digest_matches_exposed_evidence(report):
    report_without_key = {
        key: value for key, value in report.body.items() if key != "run_id"
    }
    assert digest(report_without_key) == report.digest
    assert len(report.digest) == 64
    assert report.body["run_id"] == report.digest


def test_resource_overbooking_will_not_register():
    candidate = Request(
        "A",
        "g",
        20,
        36,
        "g",
        2,
        4,
        None,
        None,
        7,
        "trained",
        "allocated",
        "OK",
        (),
        "送检",
    )
    batch = Allocation(1, 2, {"g": 2}, (candidate,))
    with pytest.raises(AccountingError, match="资源"):
        verify(batch)
    with pytest.raises(AccountingError, match="人工"):
        verify(
            replace(
                batch, capacity=10, decisions=(replace(candidate, source="incumbent"),)
            )
        )


def test_csv_links_each_row_to_its_decision(report):
    exported = list(csv.DictReader(StringIO(export_table(report.body))))
    assert {r["case_id"] for r in exported} == set(report.body["row_evidence"])
    assert len(exported) == len(report.body["decisions"])
    for candidate, projected in zip(report.body["decisions"], exported):
        assert (candidate["case_id"], candidate["status"], candidate["reason"]) == (
            projected["case_id"],
            projected["status"],
            projected["reason"],
        )


def test_comparison_excludes_unchanged_or_held_cases(original, report):
    zero = plan(original, capacity=0)
    difference = compare_records(report.body, zero.body)
    issued = {
        row["case_id"]
        for row in report.body["decisions"]
        if row["status"] == "allocated"
    }
    resumed = {row["case_id"] for row in difference if row["after"] == "allocated"}
    assert resumed == issued
    assert not any(row["after"] == "held" for row in difference)
    assert compare_records(report.body, report.body) == []


def test_exception_summary_reconciles_source_counts(report):
    intake = evidence(report.body, "ingestion")
    obs_rejections = sum(
        row["occurrences"]
        for row in intake["exceptions"]
        if row["stream"] == "observation"
    )
    assert intake["incoming"]["observations"] == intake["picked"] + obs_rejections
    assert sum(intake["reasons"].values()) == report.body["summary"]["rejected"]


def test_audit_rejects_duplicate_ids_even_with_valid_totals():
    candidate = Request(
        "CASE",
        "station",
        33,
        25,
        "station",
        1,
        8,
        None,
        None,
        4,
        "trained",
        "deferred",
        "QUOTA",
        (),
        "送检",
    )
    with pytest.raises(AccountingError, match="两次"):
        verify(Allocation(3, 0, {}, (candidate, candidate)))
