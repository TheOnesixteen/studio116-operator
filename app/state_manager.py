from __future__ import annotations

from app.models import TASK_STATES, TERMINAL_TASK_STATES


VALID_TRANSITIONS = {
    "draft": {"queued", "canceled"},
    "queued": {"planning", "canceled", "blocked", "failed"},
    "planning": {"ready", "blocked", "awaiting_approval", "failed", "canceled"},
    "ready": {"running", "blocked", "awaiting_approval", "failed", "canceled"},
    "running": {"review", "blocked", "failed", "canceled"},
    "review": {"done", "blocked", "awaiting_approval", "failed", "canceled"},
    "blocked": {"queued", "canceled", "failed"},
    "awaiting_approval": {"queued", "canceled", "blocked"},
    "done": set(),
    "failed": set(),
    "canceled": set(),
}


def validate_status(status: str) -> None:
    if status not in TASK_STATES:
        raise ValueError(f"Unknown task status: {status}")


def can_transition(from_status: str, to_status: str) -> bool:
    validate_status(from_status)
    validate_status(to_status)
    return to_status in VALID_TRANSITIONS[from_status]


def assert_transition(from_status: str, to_status: str) -> None:
    if not can_transition(from_status, to_status):
        raise ValueError(f"Invalid task transition: {from_status} -> {to_status}")


def is_terminal(status: str) -> bool:
    validate_status(status)
    return status in TERMINAL_TASK_STATES
