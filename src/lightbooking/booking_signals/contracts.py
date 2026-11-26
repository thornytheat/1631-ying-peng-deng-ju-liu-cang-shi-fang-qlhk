from dataclasses import dataclass

from ..lighting_holds.contracts import Observation


@dataclass(frozen=True)
class Signal:
    record: Observation
    vector: tuple[float, ...]
    normalized: tuple[float, ...]
    missing: tuple[str, ...]
    reference: str


@dataclass(frozen=True)
class Scale:
    fills: dict[str, float]
    centers: tuple[float, ...]
    slopes: tuple[float, ...]
    support: int


@dataclass(frozen=True)
class FeatureBank:
    as_of: int
    global_scale: Scale
    group_scales: dict[str, Scale]
    population: dict[str, int]
