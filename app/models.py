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


@dataclass(frozen=True)
class CommandResult:
    command: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False


@dataclass(frozen=True)
class HealthCheckResult:
    ok: bool
    summary: str
    checks: list[dict[str, Any]]
