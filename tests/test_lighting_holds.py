from copy import deepcopy

import pytest

from lightbooking.lighting_holds.service import known_labels, stage
from lightbooking.settings import FIELD_BOUNDS


def ingest(observations, outcomes=(), snapshot=60):
    return stage(
        {"observations": list(observations), "outcomes": list(outcomes)}, snapshot
    )


def test_conflicting_revision_is_quarantined(observation):
    # TRAP-14
    fork = {**observation, "revision": 2, "clock": observation["clock"] + 1}
    result = ingest([observation, fork, {**fork, "clock": fork["clock"] + 1}])
    assert not result.observations
    assert {issue.code: issue.occurrences for issue in result.rejections} == {
        "REVISION_CONFLICT": 2,
        "SUPERSEDED": 1,
    }


def test_pending_record_does_not_displace_visible_revision(observation):
    late = {**observation, "revision": 2, "arrived": observation["day"] + 3}
    book = ingest([late, observation])
    assert book.observations[0].revision == 1
    assert book.rejections[0].code == "AFTER_DECISION"


def test_exact_redelivery_is_audited_once(observation):
    book = ingest([observation, observation, observation])
    assert len(book.observations) == 1
    assert book.rejections[0].occurrences == 2
    assert book.rejections[0].stream == "observation"


def test_invalid_number_isolated_without_breaking_other_rows(observation):
    perturb = deepcopy(observation)
    perturb["case_id"] = "QA-BAD"
    field = next(iter(FIELD_BOUNDS))
    perturb["measurements"][field] = float("inf")
    batch = ingest([perturb, observation])
    assert [row.case_id for row in batch.observations] == [observation["case_id"]]
    assert (batch.rejections[0].code, batch.rejections[0].case_id) == (
        "INVALID",
        "QA-BAD",
    )


def test_labels_follow_historical_knowledge(observation):
    target = observation["case_id"]
    revised = [
        {"case_id": target, "available": 28, "value": 0},
        {"case_id": target, "available": 35, "value": 1},
    ]
    book = ingest([observation], revised)
    assert target not in known_labels(book, 27)
    assert known_labels(book, 32)[target].value == 0
    assert known_labels(book, 35)[target].value == 1


def test_conflicting_labels_invalidate_later_window_only(observation):
    case = observation["case_id"]
    labels = [
        {"case_id": case, "available": 26, "value": 0},
        {"case_id": case, "available": 29, "value": 0},
        {"case_id": case, "available": 29, "value": 1},
    ]
    book = ingest([observation], labels)
    assert known_labels(book, 28)[case].available == 26
    assert case not in known_labels(book, 29)
    assert book.rejections[0].occurrences == 2


def test_empty_feed_and_invalid_schema_are_distinct():
    assert not ingest([]).rejections
    with pytest.raises(ValueError, match="两份"):
        stage({"observations": []}, 60)
