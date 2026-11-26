from copy import deepcopy

import pytest

from lightbooking.lighting_holds.service import known_labels, sample, stage
from lightbooking.booking_signals.service import encode, learn_bank
from lightbooking.rental_hist_bayes.service import fit
from lightbooking.shoot_holdout.service import split
from lightbooking.engine import ROOT, plan
from lightbooking.settings import DEFAULT_DAY, FIELD_BOUNDS, GROUPS


@pytest.fixture(scope="session")
def original():
    return sample(ROOT)


@pytest.fixture
def packet(original):
    return deepcopy(original)


@pytest.fixture
def observation():
    return {
        "case_id": "QA-HD",
        "group": GROUPS[0],
        "day": 22,
        "arrived": 22,
        "revision": 1,
        "clock": 32,
        "measurements": {
            key: (0 if (lo, hi) == (0, 1) else (lo + hi) / 2)
            for key, (lo, hi) in FIELD_BOUNDS.items()
        },
    }


@pytest.fixture(scope="session")
def learning(original):
    book = stage(original, DEFAULT_DAY)
    boundary = split(DEFAULT_DAY)
    historical = stage(original, boundary.train_before - 1)
    bank = learn_bank(historical.observations, boundary.train_before)
    signals = [encode(row, bank) for row in book.observations]
    history = [encode(row, bank) for row in historical.observations]
    model = fit(history, known_labels(historical, boundary.train_before - 1))
    return book, boundary, bank, signals, history, model


@pytest.fixture(scope="session")
def report(original):
    return plan(original)
