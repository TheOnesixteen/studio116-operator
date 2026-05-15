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
            "read_only": read_only or worker in {"claude_code", "gemini_cli"},
        },
        metadata={"phase": 2, "first_slice": True},
    )


def create_live_codex_docs_only_task(
    *,
    project: str,
    title: str,
    goal: str,
    target_paths: list[str] | None = None,
    requested_by: str = "Rusty",
) -> str:
    target_paths = target_paths or ["README.md"]
    return create_task(
        project=project,
        task_type="delegated",
        title=title,
        goal=goal,
        requested_by=requested_by,
        constraints=[
            "Phase 2.1 live Codex docs-only slice",
            f"Target policy-whitelisted docs path(s) only: {', '.join(target_paths)}",
            "One writable live Codex task at a time",
            "Use isolated worktree only",
            "Canonical checkout must remain untouched",
            "Timeout after 10 minutes",
            "No deployment",
            "No service restarts",
            "No config mutation",
            "No secret reads",
            "No package installs",
            "No network-dependent work",
            "No auto-commit",
            "No auto-merge",
            "No auto-push",
            "No worktree cleanup automation",
        ],
        acceptance_criteria=[
            "Write preflight_result.json before launching Codex",
            "Launch Codex only if all required preflight checks pass",
            "Write worker_packet.json, worker_result.json, git_diff.patch, changed_files.json, and review_summary.json",
            "Stop in review after successful Codex execution",
            "Require Rusty approval before any follow-on action",
        ],
        routing={
            "worker": "codex",
            "delegation_mode": "live_codex_docs_only",
            "read_only": False,
            "target_paths": target_paths,
        },
        metadata={"phase": "2.3", "live_codex_docs_whitelist": True},
    )


def create_live_codex_tests_only_task(
    *,
    project: str,
    title: str,
    goal: str,
    target_paths: list[str] | None = None,
    requested_by: str = "Rusty",
) -> str:
    target_paths = target_paths or ["tests/test_phase24_tests_whitelist.py"]
    return create_task(
        project=project,
        task_type="delegated",
        title=title,
        goal=goal,
        requested_by=requested_by,
        constraints=[
            "Phase 2.4b live Codex tests-only slice",
            f"Target policy-whitelisted tests path(s) only: {', '.join(target_paths)}",
            "One writable live Codex task at a time",
            "Use isolated worktree only",
            "Canonical checkout must remain untouched",
            "Timeout after 10 minutes",
            "No app code changes",
            "No infrastructure changes",
            "No config mutation",
            "No runtime file changes",
            "No deployment",
            "No service restarts",
            "No secret reads",
            "No package installs",
            "No network-dependent work",
            "No auto-commit",
            "No auto-merge",
            "No auto-push",
            "No worktree cleanup automation",
        ],
        acceptance_criteria=[
            "Write preflight_result.json before launching Codex",
            "Launch Codex only if all required preflight checks pass",
            "Write worker_packet.json, worker_result.json, git_diff.patch, changed_files.json, and review_summary.json",
            "Stop in review after successful Codex execution",
            "Require Rusty approval before any follow-on action",
        ],
        routing={
            "worker": "codex",
            "delegation_mode": "live_codex_tests_only",
            "read_only": False,
            "target_paths": target_paths,
        },
        metadata={"phase": "2.4b", "live_codex_tests_whitelist": True, "test_content_hardening": True},
    )


def create_live_codex_policy_file_task(
    *,
    project: str,
    title: str,
    goal: str,
    target_paths: list[str] | None = None,
    requested_by: str = "Rusty",
) -> str:
    target_paths = target_paths or ["app/policies.py"]
    return create_task(
        project=project,
        task_type="delegated",
        title=title,
        goal=goal,
        requested_by=requested_by,
        constraints=[
            "Phase 2.5a live Codex policy-file slice",
            f"Target policy-whitelisted policy file only: {', '.join(target_paths)}",
            "One writable live Codex task at a time",
            "Use isolated worktree only",
            "Canonical checkout must remain untouched",
            "Timeout after 10 minutes",
            "No app code changes outside app/policies.py",
            "No tests changes",
            "No registry changes",
            "No infrastructure changes",
            "No config mutation",
            "No runtime file changes",
            "No deployment",
            "No service restarts",
            "No secret reads",
            "No package installs",
            "No network-dependent work",
            "No auto-commit",
            "No auto-merge",
            "No auto-push",
            "No worktree cleanup automation",
        ],
        acceptance_criteria=[
            "Write preflight_result.json before launching Codex",
            "Launch Codex only if all required preflight checks pass",
            "Write worker_packet.json, worker_result.json, git_diff.patch, changed_files.json, and review_summary.json",
            "Stop in review after successful Codex execution",
            "Require Rusty approval before any follow-on action",
        ],
        routing={
            "worker": "codex",
            "delegation_mode": "live_codex_policy_file_only",
            "read_only": False,
            "target_paths": target_paths,
        },
        metadata={"phase": "2.5a", "live_codex_policy_file_whitelist": True, "policy_file_content_hardening": True},
    )


def create_live_codex_model_file_task(
    *,
    project: str,
    title: str,
    goal: str,
    target_paths: list[str] | None = None,
    requested_by: str = "Rusty",
) -> str:
    target_paths = target_paths or ["app/models.py"]
    return create_task(
        project=project,
        task_type="delegated",
        title=title,
        goal=goal,
        requested_by=requested_by,
        constraints=[
            "Phase 2.6a live Codex model-file slice",
            f"Target policy-whitelisted model file only: {', '.join(target_paths)}",
            "One writable live Codex task at a time",
            "Use isolated worktree only",
            "Canonical checkout must remain untouched",
            "Timeout after 10 minutes",
            "No app code changes outside app/models.py",
            "No tests changes",
            "No registry changes",
            "No infrastructure changes",
            "No config mutation",
            "No runtime file changes",
            "No deployment",
            "No service restarts",
            "No secret reads",
            "No package installs",
            "No network-dependent work",
            "No auto-commit",
            "No auto-merge",
            "No auto-push",
            "No worktree cleanup automation",
        ],
        acceptance_criteria=[
            "Write preflight_result.json before launching Codex",
            "Launch Codex only if all required preflight checks pass",
            "Write worker_packet.json, worker_result.json, git_diff.patch, changed_files.json, and review_summary.json",
            "Stop in review after successful Codex execution",
            "Require Rusty approval before any follow-on action",
        ],
        routing={
            "worker": "codex",
            "delegation_mode": "live_codex_model_file_only",
            "read_only": False,
            "target_paths": target_paths,
        },
        metadata={"phase": "2.6a", "live_codex_model_file_whitelist": True, "model_file_content_hardening": True},
    )


def create_live_codex_scaffold_only_task(
    *,
    project: str,
    title: str,
    goal: str,
    target_paths: list[str] | None = None,
    requested_by: str = "Rusty",
) -> str:
    target_paths = target_paths or ["app/__init__.py"]
    return create_task(
        project=project,
        task_type="delegated",
        title=title,
        goal=goal,
        requested_by=requested_by,
        constraints=[
            "Phase 2.10e live Codex external scaffold-only slice",
            f"Target policy-whitelisted scaffold path(s) only: {', '.join(target_paths)}",
            "One writable live Codex task at a time",
            "Use isolated worktree only",
            "Canonical checkout must remain untouched until review approval",
            "Timeout after 10 minutes",
            "No app code changes outside approved scaffold paths",
            "No app/ai_generation.py changes",
            "No email sender changes",
            "No infrastructure changes",
            "No runtime config changes",
            "No publishing job changes",
            "No deployment",
            "No service restarts",
            "No secret reads",
            "No package installs",
            "No network-dependent work",
            "No auto-commit",
            "No auto-merge",
            "No auto-push",
            "No worktree cleanup automation",
        ],
        acceptance_criteria=[
            "Write preflight_result.json before launching Codex",
            "Launch Codex only if all required preflight checks pass",
            "Write worker_packet.json, worker_result.json, git_diff.patch, changed_files.json, and review_summary.json",
            "Stop in review after successful Codex execution",
            "Require Rusty approval before any follow-on action",
        ],
        routing={
            "worker": "codex",
            "delegation_mode": "live_codex_scaffold_only",
            "read_only": False,
            "target_paths": target_paths,
        },
        metadata={"phase": "2.10e", "live_codex_external_scaffold_whitelist": True},
    )
