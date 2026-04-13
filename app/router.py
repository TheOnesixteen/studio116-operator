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


def create_delegated_dry_run_task(
    *,
    project: str,
    title: str,
    goal: str,
    worker: str,
    read_only: bool = False,
    requested_by: str = "Rusty",
) -> str:
    return create_task(
        project=project,
        task_type="delegated",
        title=title,
        goal=goal,
        requested_by=requested_by,
        constraints=[
            "Phase 2 first slice dry-run only",
            "Do not launch delegated workers",
            "No deployment",
            "No service restarts",
            "No config mutation",
            "No secret reads",
            "No dashboard or webhook work",
            "No worktree cleanup automation",
        ],
        acceptance_criteria=[
            "Acquire scheduler-owned SQLite locks",
            "Write worker packet artifact",
            "Record intended worker command",
            "Stop before launching the worker",
        ],
        routing={
            "worker": worker,
            "delegation_mode": "dry_run",
            "read_only": read_only or worker == "claude_code",
        },
        metadata={"phase": 2, "first_slice": True},
    )
