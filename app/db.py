from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import ensure_runtime_dirs, get_settings


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    settings = get_settings()
    ensure_runtime_dirs(settings)
    conn = sqlite3.connect(str(db_path or settings.db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    settings = get_settings()
    ensure_runtime_dirs(settings)
    schema = settings.schema_path.read_text(encoding="utf-8")
    with connect(db_path) as conn:
        conn.executescript(schema)
        conn.commit()


@contextmanager
def transaction(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
