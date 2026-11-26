from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from lightbooking.hold_registry.contracts import RevisionConflict, UnknownRelease
from lightbooking.hold_registry.service import list_releases, read_release, register
from lightbooking.engine import plan


def test_stale_generation_keeps_prior(tmp_path, report, original):
    # TRAP-26
    store = tmp_path / "archive.db"
    first = register(store, report, 0)
    alternative = plan(original, capacity=0)
    with pytest.raises(RevisionConflict, match="版本"):
        register(store, alternative, 0)
    assert read_release(store, 1).run_id == first.run_id
    assert len(list_releases(store)) == 1


def test_registration_is_idempotent_and_receipt_is_complete(tmp_path, report):
    store = tmp_path / "archive.db"
    new = register(store, report, 0)
    retry = register(store, report, 0)
    assert new.generation == retry.generation == 1
    assert retry.replayed and not new.replayed
    saved = read_release(store, 1)
    assert saved.run_id == report.digest
    assert len(saved.evidence["row_evidence"]) == report.quantity
    assert saved.evidence["summary"] == report.body["summary"]


def test_history_is_paginated_and_links_previous_run(tmp_path, report, original):
    store = tmp_path / "archive.db"
    first = register(store, report, 0)
    alternative = plan(original, capacity=0)
    second = register(store, alternative, 1)
    assert second.prior_run == first.run_id and second.generation == 2
    assert [entry.generation for entry in list_releases(store, limit=1)] == [2]
    assert [entry.generation for entry in list_releases(store, limit=1, before=2)] == [
        1
    ]


def test_concurrent_double_registration_creates_one_version(tmp_path, report):
    store = tmp_path / "archive.db"
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: register(store, report, 0), range(2)))
    assert sorted(entry.replayed for entry in results) == [False, True]
    assert len(list_releases(store)) == 1


def test_new_freeze_cannot_be_overwritten_by_old_snapshot(tmp_path, report, original):
    store = tmp_path / "archive.db"
    register(store, report, 0)
    older = plan(original, as_of=report.as_of - 1)
    with pytest.raises(RevisionConflict, match="旧快照"):
        register(store, older, 1)
    assert list_releases(store)[0].as_of == report.as_of


def test_body_tamper_and_missing_entry_are_detected(tmp_path, report):
    store = tmp_path / "archive.db"
    tampered = replace(report, body={**report.body, "project": "异地单据"})
    with pytest.raises(ValueError, match="校验"):
        register(store, tampered, 0)
    with pytest.raises(UnknownRelease):
        read_release(store, 1)


def test_empty_batch_cannot_become_official_release(tmp_path):
    result = plan({"observations": [], "outcomes": []})
    assert result.quantity == 0
    with pytest.raises(ValueError, match="空单据"):
        register(tmp_path / "archive.db", result, 0)
