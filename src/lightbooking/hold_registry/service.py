from datetime import datetime, timezone
import json

from ..checkout_reconcile.service import canonical, digest
from .contracts import Release, ReleaseDigest, RevisionConflict, UnknownRelease
from .storage import current, database, duplicate, get, insert, recent


def _restore(row, replayed=False):
    report = json.loads(row["report"])
    if (
        report.get("run_id") != row["digest"]
        or digest({k: v for k, v in report.items() if k != "run_id"}) != row["digest"]
    ):
        raise ValueError("已登记的运行证据校验不通过")
    return Release(
        row["generation"],
        row["digest"],
        row["as_of"],
        row["created"],
        replayed,
        row["prior_run"],
        report,
    )


def _validated_body(delivery):
    if not delivery.quantity:
        raise ValueError("空单据批次不允许登记")
    body = delivery.body
    if (
        body.get("run_id") != delivery.digest
        or body.get("as_of") != delivery.as_of
        or len(body.get("decisions", [])) != delivery.quantity
        or body["summary"]["used"] != delivery.consumed
        or digest({k: v for k, v in body.items() if k != "run_id"}) != delivery.digest
    ):
        raise ValueError("待登记的运行证据校验不通过")
    return canonical(body)


def register(path, delivery, expected: int) -> Release:
    if type(expected) is not int or expected < 0:
        raise ValueError("登记需提供非负的当前版本号")
    body = _validated_body(delivery)
    with database(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = duplicate(conn, delivery.digest)
        if existing is not None:
            result = _restore(existing, replayed=True)
            conn.commit()
            return result
        head = current(conn)
        latest = head["generation"] if head else 0
        if latest != expected:
            raise RevisionConflict(f"当前已登记的版本是 {latest}，请重新核对待发布单据")
        if head is not None and head["as_of"] > delivery.as_of:
            raise RevisionConflict("旧快照不能覆盖已经登记的新快照")
        previous = head["digest"] if head else None
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        saved = insert(conn, latest + 1, delivery, now, previous, body)
        result = _restore(saved)
        conn.commit()
    return result


def list_releases(path, limit=30, before=None):
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or (before is not None and (type(before) is not int or before <= 0))
    ):
        raise ValueError("登记页参数不在范围内")
    with database(path) as conn:
        return [
            ReleaseDigest(
                row["generation"],
                row["digest"],
                row["as_of"],
                row["quantity"],
                row["consumed"],
                row["created"],
            )
            for row in recent(conn, limit, before)
        ]


def read_release(path, generation):
    with database(path) as conn:
        row = get(conn, generation)
        if row is None:
            raise UnknownRelease("登记版本不存在")
        return _restore(row)
