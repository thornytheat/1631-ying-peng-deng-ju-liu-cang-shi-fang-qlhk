from collections import defaultdict
from statistics import median

from ..lighting_holds.contracts import Observation
from ..settings import FIELD_BOUNDS, GROUPS, REPORT_LAG, SIGNAL_NAMES
from .contracts import FeatureBank, Scale, Signal
from .coverage import fit_audit, measure_sensitivity, reference_summary
from .domain import default_fills, domain_factors, robust_scale, usable_report


MIN_GROUP = 14


def make_scale(rows: list[Observation], backup: dict[str, float]) -> Scale:
    fills = {}
    for field in FIELD_BOUNDS:
        seen = [
            item.reported[field]
            for item in rows
            if item.reported.get(field) is not None
        ]
        fills[field] = median(seen) if seen else backup[field]
    vectors = [domain_factors(usable_report(item.reported, fills)) for item in rows]
    pivots = (
        [robust_scale(list(column)) for column in zip(*vectors)]
        if vectors
        else [(0.0, 1.0)] * len(SIGNAL_NAMES)
    )
    centers, slopes = zip(*pivots)
    return Scale(fills, centers, slopes, len(rows))


def learn_bank(observations: tuple[Observation, ...], cutoff: int) -> FeatureBank:
    # 拟合统计量使用决定时已见且训练冻结前到达的测量。
    history = [
        item
        for item in observations
        if item.day < cutoff
        and item.arrived < cutoff
        and item.arrived <= item.day + REPORT_LAG
    ]
    by_group = defaultdict(list)
    for item in history:
        by_group[item.group].append(item)
    population = {name: len(by_group[name]) for name in GROUPS}
    global_scale = make_scale(history, default_fills())
    local = {
        group: make_scale(rows, global_scale.fills)
        for group, rows in by_group.items()
        if len(rows) >= MIN_GROUP
    }
    return FeatureBank(cutoff, global_scale, local, population)


def encode(record: Observation, bank: FeatureBank) -> Signal:
    # 中心与尺度用同一份全局参考；分组尺度用于缺测插补，保留物理组间差别。
    subgroup = bank.group_scales.get(record.group)
    scale = subgroup or bank.global_scale
    reported = usable_report(record.reported, scale.fills)
    raw = domain_factors(reported)
    norm = tuple(
        max(-12.0, min(12.0, (value - center) / step))
        for value, center, step in zip(
            raw, bank.global_scale.centers, bank.global_scale.slopes
        )
    )
    missing = tuple(key for key, value in record.reported.items() if value is None)
    return Signal(record, raw, norm, missing, record.group if subgroup else "全域")


def trace(signal: Signal) -> dict:
    return {
        "case_id": signal.record.case_id,
        "feature_reference": signal.reference,
        "missing": list(signal.missing),
        "features": dict(zip(SIGNAL_NAMES, signal.vector)),
        "standardized": dict(zip(SIGNAL_NAMES, signal.normalized)),
        "measurements": signal.record.reported,
        "decision_day": signal.record.day + REPORT_LAG,
    }


def ranges(signals: list[Signal]) -> dict:
    evidence = {}
    for index, name in enumerate(SIGNAL_NAMES):
        column = sorted(item.vector[index] for item in signals)
        if column:
            evidence[name] = {
                "min": column[0],
                "median": median(column),
                "max": column[-1],
            }
    return evidence
