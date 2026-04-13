from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.config import ensure_runtime_dirs, get_settings
from app.db import transaction
from app.events import utc_now


def write_json_artifact(
    *,
    task_id: str,
    run_id: str,
    artifact_type: str,
    label: str,
    data: dict[str, Any],
) -> Path:
    settings = get_settings()
    ensure_runtime_dirs(settings)
    task_dir = settings.artifacts_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    path = task_dir / f"{run_id}-{artifact_type}.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO task_artifacts (
              id, task_id, run_id, artifact_type, path, label, created_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                task_id,
                run_id,
                artifact_type,
                str(path),
                label,
                utc_now(),
                "{}",
            ),
        )
    return path
