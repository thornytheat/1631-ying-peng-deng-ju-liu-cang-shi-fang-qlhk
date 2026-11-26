from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    case_id: str
    group: str
    day: int
    arrived: int
    revision: int
    clock: int
    reported: dict[str, float | None]


@dataclass(frozen=True)
class Outcome:
    case_id: str
    available: int
    value: float
    occurred: bool


@dataclass(frozen=True)
class Rejection:
    code: str
    stream: str
    case_id: str
    detail: str
    occurrences: int = 1


@dataclass(frozen=True)
class Intake:
    observations: tuple[Observation, ...]
    outcomes: tuple[Outcome, ...]
    rejections: tuple[Rejection, ...]
    source_counts: dict[str, int]
