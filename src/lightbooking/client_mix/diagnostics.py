from statistics import mean

from ..settings import WATCH_FEATURE


def shift_alerts(shifts):
    results = []
    sensitivity = 1.3499999999999999
    for name, cohort in sorted(shifts.groups.items()):
        for feature, data in cohort.distributions.items():
            delta = (
                None
                if data.get("recent_median") is None
                else data["recent_median"] - data["reference_median"]
            )
            if delta is None:
                continue
            relative = abs(delta) / max(0.05, abs(data["reference_median"]))
            priority = round(
                relative * (sensitivity if feature == WATCH_FEATURE else 1)
                + data["outside"],
                7,
            )
            if priority >= 0.42 or cohort.status in {"LOW_SUPPORT", "REGIME_CHANGED"}:
                results.append(
                    {
                        "group": name,
                        "feature": feature,
                        "median_difference": delta,
                        "outside_share": data["outside"],
                        "priority": priority,
                        "decision_state": cohort.status,
                    }
                )
    return sorted(
        results, key=lambda item: (-item["priority"], item["group"], item["feature"])
    )


def readiness(shifts):
    cohorts = list(shifts.groups.values())
    populated = [c for c in cohorts if c.reference and c.live]
    participating = sum(c.live for c in populated)
    return {
        "populated_groups": len(populated),
        "expected_groups": len(cohorts),
        "paired_candidates": participating,
        "reference_share": participating / shifts.assessed if shifts.assessed else 0.0,
        "mean_observed_gap": mean(c.missing_rate_delta for c in populated)
        if populated
        else 0.0,
    }
