from __future__ import annotations

from app.task_engine import HEALTH_CHECK_GOAL, HEALTH_CHECK_TITLE, create_task


def create_health_check_task() -> str:
    return create_task(
        project="vps",
        task_type="health_check",
        title=HEALTH_CHECK_TITLE,
        goal=HEALTH_CHECK_GOAL,
        acceptance_criteria=[
            "Inspect Caddy status without restarting or editing configuration",
            "Inspect kairoke.service status without restarting or editing service files",
            "Inspect Docker container health without mutating containers",
        ],
        metadata={"phase": 1, "read_only": True},
    )
