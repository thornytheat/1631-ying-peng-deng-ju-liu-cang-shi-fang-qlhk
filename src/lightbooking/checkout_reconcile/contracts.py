from dataclasses import dataclass


@dataclass(frozen=True)
class Delivery:
    digest: str
    as_of: int
    quantity: int
    consumed: int
    body: dict


class AccountingError(ValueError):
    """分派与证据数量不平，停止登记。"""
