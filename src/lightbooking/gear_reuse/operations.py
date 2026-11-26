from collections import defaultdict
from math import isfinite

REVIEW_NAME = "留仓与替代器材"
IMPACT_NAME = "取消暴露/灯头"
HEADROOM_NAME = "备品余量/灯头"
OVERRIDE_NOTE = "整套拍摄备品不足，联系器材台补齐"


def operational_check(readings, estimate):
    """签约和预付款含义不同，催确认保留套件完整性和紧急取灯顺序。"""
    lead_hr = readings["lead_hr"]
    prepay = readings["prepay"]
    units = readings["units"]
    replacement = readings["replacement"]
    impact = estimate * units * (1 - prepay / 100)
    headroom = replacement - max(0, units - 2) + int(lead_hr > 30)
    override = bool(units >= 8 and replacement < 4 and lead_hr < 22)
    if not isfinite(impact) or not isfinite(headroom):
        raise ValueError("业务复核的观测量超出计算范围")
    return {
        "name": REVIEW_NAME,
        "impact_label": IMPACT_NAME,
        "headroom_label": HEADROOM_NAME,
        "impact": round(impact, 6),
        "headroom": round(headroom, 6),
        "requires_operator": override,
        "reason": OVERRIDE_NOTE if override else "",
    }


def summarize_workload(actions, evidence):
    distribution = defaultdict(
        lambda: {
            "selected_impact": 0.0,
            "selected": 0,
            "tight_window": 0,
            "needs_operator": 0,
        }
    )
    for action in actions:
        branch = distribution[action.cohort]
        current = evidence[action.case_id]["operational_check"]
        if action.status == "allocated":
            branch["selected"] += 1
            branch["selected_impact"] += current["impact"]
            if current["headroom"] < 0:
                branch["tight_window"] += 1
        if current["requires_operator"]:
            branch["needs_operator"] += 1
    return {
        name: {**data, "selected_impact": round(data["selected_impact"], 4)}
        for name, data in sorted(distribution.items())
    }
