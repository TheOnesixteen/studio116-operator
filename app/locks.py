from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from typing import Iterator

from app.db import transaction
from app.events import record_event, utc_now


def acquire_lock(
    *,
    lock_type: str,
    resource_key: str,
    task_id: str | None = None,
    run_id: str | None = None,
    worker_name: str | None = None,
    metadata: dict | None = None,
) -> str:
    lock_id = str(uuid.uuid4())
    now = utc_now()
    try:
        with transaction() as conn:
            conn.execute(
                """
                INSERT INTO locks (
                  id, lock_type, resource_key, task_id, run_id, worker_name,
                  status, acquired_at, heartbeat_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    lock_id,
                    lock_type,
                    resource_key,
                    task_id,
                    run_id,
                    worker_name,
                    now,
                    now,
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise RuntimeError(f"Active lock exists for {lock_type}:{resource_key}") from exc
    record_event("lock_acquired", f"Acquired {lock_type}:{resource_key}", task_id=task_id, run_id=run_id)
    return lock_id


def heartbeat_lock(lock_id: str) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE locks SET heartbeat_at = ? WHERE id = ? AND status = 'active'",
            (utc_now(), lock_id),
        )


def attach_run_to_lock(lock_id: str, run_id: str) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE locks SET run_id = ? WHERE id = ? AND status = 'active'",
            (run_id, lock_id),
        )


def release_lock(lock_id: str) -> None:
    with transaction() as conn:
        row = conn.execute("SELECT task_id, run_id, lock_type, resource_key FROM locks WHERE id = ?", (lock_id,)).fetchone()
        conn.execute(
            "UPDATE locks SET status = 'released', released_at = ? WHERE id = ? AND status = 'active'",
            (utc_now(), lock_id),
        )
    if row:
        record_event(
            "lock_released",
            f"Released {row['lock_type']}:{row['resource_key']}",
            task_id=row["task_id"],
            run_id=row["run_id"],
        )


@contextmanager
def scheduler_lock(task_id: str | None = None, run_id: str | None = None) -> Iterator[str]:
    lock_id = acquire_lock(
        lock_type="scheduler",
        resource_key="run_next",
        task_id=task_id,
        run_id=run_id,
        worker_name="scheduler",
        metadata={"owner": "scheduler"},
    )
    try:
        yield lock_id
    finally:
        release_lock(lock_id)
