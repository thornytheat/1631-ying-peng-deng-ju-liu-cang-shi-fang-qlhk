from contextlib import contextmanager
from pathlib import Path
import sqlite3


DDL = """
CREATE TABLE IF NOT EXISTS releases (
    generation INTEGER PRIMARY KEY CHECK (generation > 0),
    digest TEXT NOT NULL UNIQUE,
    as_of INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    consumed INTEGER NOT NULL CHECK (consumed >= 0),
    created TEXT NOT NULL,
    prior_run TEXT REFERENCES releases(digest),
    report TEXT NOT NULL
)
"""


@contextmanager
def database(path):
    location = Path(path)
    location.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(location, timeout=8, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(DDL)
        yield conn
    finally:
        conn.close()


def current(conn):
    return conn.execute(
        "SELECT * FROM releases ORDER BY generation DESC LIMIT 1"
    ).fetchone()


def get(conn, generation):
    return conn.execute(
        "SELECT * FROM releases WHERE generation = ?", (generation,)
    ).fetchone()


def duplicate(conn, checksum):
    return conn.execute(
        "SELECT * FROM releases WHERE digest = ?", (checksum,)
    ).fetchone()


def recent(conn, limit, before):
    return conn.execute(
        """
        SELECT generation, digest, as_of, quantity, consumed, created FROM releases
        WHERE (? IS NULL OR generation < ?) ORDER BY generation DESC LIMIT ?
        """,
        (before, before, limit),
    ).fetchall()


def insert(conn, generation, delivery, created, previous, body):
    conn.execute(
        """
        INSERT INTO releases (generation,digest,as_of,quantity,consumed,created,prior_run,report)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            generation,
            delivery.digest,
            delivery.as_of,
            delivery.quantity,
            delivery.consumed,
            created,
            previous,
            body,
        ),
    )
    return get(conn, generation)
