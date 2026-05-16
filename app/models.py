from __future__ import annotations

from dataclasses import dataclass, field
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


# Shared result containers for operator checks.
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


@dataclass(frozen=True)
class StandardizedTask:
    """
    The canonical task object produced by the intake layer.
    Both `operator ingest` and `operator do` compile down to this before
    the engine sees anything. All required fields come before optional ones
    to satisfy Python dataclass ordering rules.
    """
    # Required — Identity
    title: str
    goal: str

    # Required — Project + Worker
    project: str
    task_type: str
    agent: str
    delegation_mode: str

    # Required — Scope + Paths
    scope: list[str]
    target_paths: list[str]
    blocked_paths: list[str]
    origin_directory: str

    # Required — Task Content
    steps: list[str]
    acceptance_criteria: list[str]

    # Required — Risk + Normalization
    risk_level: str
    normalization_path: str

    # Optional — Identity
    requested_by: str = "rusty"
    priority: int = 10

    # Optional — Risk
    confidence: float = 0.0

    # Optional — Policy Enforcement (defaults are maximally restrictive)
    write_intent: bool = False
    read_only: bool = True
    allow_file_creation: bool = False
    max_changed_files: int = 1
    deployment_allowed: bool = False

    # Optional — Approval Gates (defaults require human in the loop)
    requires_confirmation: bool = True
    requires_human_approval: bool = True
    requires_gemini_review: bool = False

    # Optional — Source Context (preserved for audit trail)
    source_context: dict = field(default_factory=dict)
    # {
    #   "entrypoint": "do | ingest",
    #   "raw_input": "original string or spec path",
    #   "spec_path": "path or null",
    #   "referenced_artifacts": []
    # }

    # Optional — Routing Transparency
    routing_reason: str = ""
    normalization_notes: list[str] = field(default_factory=list)
