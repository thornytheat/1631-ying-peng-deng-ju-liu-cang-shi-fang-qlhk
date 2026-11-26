import json
from math import isfinite
from pathlib import Path
import re

from ..settings import FIELD_BOUNDS, GROUPS, REPORT_LAG, TARGET
from .contracts import Observation, Outcome


CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,43}\Z")
MAX_RECORDS = 2500


def read_stream(path: Path) -> list:
    items = []
    with path.open(encoding="utf-8-sig") as source:
        for line_no, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"{path.name} 第 {line_no} 行 JSON 格式错误") from exc
            items.append(item)
            if len(items) > MAX_RECORDS:
                raise ValueError(f"{path.name} 记录超过 {MAX_RECORDS} 条")
    return items


def number(raw: object, label: str) -> float:
    if type(raw) not in (int, float):
        raise ValueError(f"{label} 必须为数值")
    try:
        value = float(raw)
    except OverflowError as exc:
        raise ValueError(f"{label} 超出数值范围") from exc
    if not isfinite(value):
        raise ValueError(f"{label} 必须为有限值")
    return value


def integer(raw: object, low: int, high: int, label: str) -> int:
    if type(raw) is not int or not low <= raw <= high:
        raise ValueError(f"{label} 应是 {low} 至 {high} 的整数")
    return raw


def identity(row: object) -> str:
    if (
        not isinstance(row, dict)
        or not isinstance(row.get("case_id"), str)
        or not CASE_ID.fullmatch(row["case_id"])
    ):
        raise ValueError("单据编号缺失或格式不合法")
    return row["case_id"]


def observation(row: dict) -> Observation:
    case_id = identity(row)
    day = integer(row.get("day"), 1, 36_500, "发生日")
    arrived = integer(row.get("arrived"), day, 36_500, "入账日")
    revision = integer(row.get("revision"), 1, 10_000, "修订号")
    if not isinstance(row.get("group"), str) or row["group"] not in GROUPS:
        raise ValueError("业务分组不在档案内")
    clock = integer(row.get("clock"), 0, 95, "15 分钟时段")
    fields = row.get("measurements")
    if not isinstance(fields, dict) or set(fields) - FIELD_BOUNDS.keys():
        raise ValueError("测量字段与单据档案不一致")
    reported = {}
    for field, (lower, upper) in FIELD_BOUNDS.items():
        value = fields.get(field)
        if value is not None:
            value = number(value, field)
            if not lower <= value <= upper:
                raise ValueError(f"{field} 超出设备计量范围 [{lower}, {upper}]")
            if upper == 1 and lower == 0 and value not in (0, 1):
                raise ValueError(f"{field} 只接收 0 或 1")
        reported[field] = value
    return Observation(case_id, row["group"], day, arrived, revision, clock, reported)


def outcome(row: dict) -> Outcome:
    case_id = identity(row)
    available = integer(row.get("available"), 1, 36_500, "结果确认日")
    value = number(row.get("value"), "结果值")
    occurred = row.get("occurred", True)
    if type(occurred) is not bool:
        raise ValueError("事件状态应为真假值")
    if value < 0 or value > 1_000_000:
        raise ValueError("结果不在可接受的观测范围")
    if TARGET in {"binary", "anomaly"} and value not in (0.0, 1.0):
        raise ValueError("事件标签须为 0 或 1")
    if TARGET == "count" and int(value) != value:
        raise ValueError("计数目标须为整数")
    if TARGET != "censored" and not occurred:
        raise ValueError("该项目的观测结果不接受删失标志")
    return Outcome(case_id, available, value, occurred)


def arrival_reason(row: Observation, as_of: int) -> str:
    if row.day > as_of or row.arrived > as_of:
        return "OUTSIDE_SNAPSHOT"
    if row.arrived > row.day + REPORT_LAG:
        return "AFTER_DECISION"
    return ""
