from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import ensure_runtime_dirs, get_settings
from app.db import transaction


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(text: str | None) -> str:
    if not text:
        return ""
    redacted = text
    markers = ("api_key", "apikey", "token", "secret", "password", "bearer")
    lines = []
    for line in redacted.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in markers):
            lines.append("[redacted sensitive line]")
        else:
            lines.append(line)
    return "\n".join(lines)


def write_operator_log(message: str, path: Path | None = None) -> None:
    settings = get_settings()
    ensure_runtime_dirs(settings)
    log_path = path or settings.operator_log_path
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"{utc_now()} {message}\n")


def record_event(
    event_type: str,
    message: str,
    *,
    task_id: str | None = None,
    run_id: str | None = None,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
) -> str:
    event_id = str(uuid.uuid4())
    safe_message = redact(message)
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO events (
              id, task_id, run_id, event_type, level, message, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                task_id,
                run_id,
                event_type,
                level,
                safe_message,
                utc_now(),
                json.dumps(metadata or {}, sort_keys=True),
            ),
        )
    write_operator_log(f"{level} {event_type} task={task_id or '-'} run={run_id or '-'} {safe_message}")
    return event_id
