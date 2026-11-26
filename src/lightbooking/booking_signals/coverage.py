from collections import Counter, defaultdict
from math import fsum

from ..settings import CRITICAL_FIELDS, FIELD_LABELS, SIGNAL_NAMES
from .domain import domain_factors


def fit_audit(signals, reference_bank):
    missing_by_group = defaultdict(Counter)
    encode_sources = Counter()
    for entry in signals:
        missing_by_group[entry.record.group].update(entry.missing)
        encode_sources[entry.reference] += 1
    return {
        "reference_before": reference_bank.as_of,
        "fitted_cases": reference_bank.global_scale.support,
        "reference_groups": reference_bank.population,
        "used_references": dict(encode_sources),
        "missing_by_group": {k: dict(v) for k, v in missing_by_group.items()},
        "variable_scale": dict(zip(SIGNAL_NAMES, reference_bank.global_scale.slopes)),
        "critical_labels": [FIELD_LABELS[key] for key in sorted(CRITICAL_FIELDS)],
    }


def measure_sensitivity(signal, reference_bank, fields):
    scale = reference_bank.group_scales.get(
        signal.record.group, reference_bank.global_scale
    )
    measured = dict(signal.record.reported)
    filled = {
        key: scale.fills[key] if value is None else value
        for key, value in measured.items()
    }
    influence = []
    for key in fields:
        if measured[key] is None:
            continue
        neutral = {**filled, key: scale.fills[key]}
        alternatives = domain_factors(neutral)
        changes = {
            name: (v - a) / width
            for name, v, a, width in zip(
                SIGNAL_NAMES,
                signal.vector,
                alternatives,
                reference_bank.global_scale.slopes,
            )
        }
        influence.append(
            {
                "measurement": key,
                "name": FIELD_LABELS[key],
                "reference_value": neutral[key],
                "effect": changes,
                "scaled_distance": fsum(abs(n) for n in changes.values()),
            }
        )
    return sorted(
        influence, key=lambda item: (-item["scaled_distance"], item["measurement"])
    )


def reference_summary(reference_bank):
    groups = reference_bank.group_scales
    return {
        "cutoff": reference_bank.as_of,
        "sample_count": reference_bank.global_scale.support,
        "reference_sources": {
            name: ref.support for name, ref in sorted(groups.items())
        },
        "center": dict(zip(SIGNAL_NAMES, reference_bank.global_scale.centers)),
        "scale": dict(zip(SIGNAL_NAMES, reference_bank.global_scale.slopes)),
    }
