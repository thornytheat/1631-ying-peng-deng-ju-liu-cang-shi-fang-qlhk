from dataclasses import dataclass


class RevisionConflict(ValueError):
    """原先检查过的版本已不再是当前草案基线。"""


class UnknownRelease(LookupError):
    """找不到所请求的已登记版本。"""


@dataclass(frozen=True)
class Release:
    generation: int
    run_id: str
    as_of: int
    registered_at: str
    replayed: bool
    prior_run: str | None
    evidence: dict


@dataclass(frozen=True)
class ReleaseDigest:
    generation: int
    run_id: str
    as_of: int
    quantity: int
    consumed: int
    registered_at: str
