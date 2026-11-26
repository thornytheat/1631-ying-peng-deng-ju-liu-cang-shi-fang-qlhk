from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    cohort: str
    status: str
    reference: int
    live: int
    worst_feature: str | None
    max_psi: float | None
    missing_rate_delta: float
    extremes: dict[str, float]
    distributions: dict[str, dict]


@dataclass(frozen=True)
class DriftReport:
    groups: dict[str, Check]
    assessed: int
    blocked: int


@dataclass(frozen=True)
class Gate:
    allowed: bool
    reasons: tuple[str, ...]
    source: str
