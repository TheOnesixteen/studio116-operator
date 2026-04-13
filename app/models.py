from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TASK_STATES = (
    "draft",
    "queued",
    "planning",
    "ready",
    "running",
    "review",
    "blocked",
    "awaiting_approval",
    "done",
    "failed",
    "canceled",
)


TERMINAL_TASK_STATES = {"done", "failed", "canceled"}
HEALTH_STATUSES = ("ok", "warning", "failed")


@dataclass(frozen=True)
class CommandResult:
    command: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


@dataclass(frozen=True)
class HealthCheckResult:
    overall_status: str
    task_succeeded: bool
    summary: str
    key_findings: list[str]
    checks: list[dict[str, Any]]
