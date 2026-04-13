from __future__ import annotations

from pathlib import Path
from typing import Any


EXPECTED_OUTPUT_CONTRACT = {
    "summary": "required",
    "files_touched": "required",
    "tests_run": "required",
    "blockers": "required",
    "approval_requests": "required",
    "secret_exposure_check": "required",
}


BASE_FORBIDDEN_ACTIONS = [
    "deploy_to_production",
    "systemctl_restart",
    "systemctl_stop",
    "edit_caddy_config",
    "edit_live_env_files",
    "dns_or_ssl_changes",
    "delete_database_records",
    "delete_production_data",
    "expose_api_keys_in_output",
    "expose_secrets_in_logs",
    "auto_deploy_without_approval",
    "run_unknown_scripts_from_internet",
]


def worker_packet(
    *,
    worker: str,
    task: dict[str, Any],
    run_id: str,
    mode: str,
    allowed_actions: list[str],
    constraints: list[str],
    branch_name: str | None,
    worktree_path: Path | None,
    read_only: bool,
) -> dict[str, Any]:
    return {
        "phase": "2",
        "mode": mode,
        "worker": worker,
        "read_only": read_only,
        "task_id": task["id"],
        "run_id": run_id,
        "project": task["project"],
        "title": task["title"],
        "goal": task["goal"],
        "constraints": constraints,
        "allowed_actions": allowed_actions,
        "forbidden_actions": BASE_FORBIDDEN_ACTIONS,
        "branch_name": branch_name,
        "worktree_path": str(worktree_path) if worktree_path else None,
        "expected_output": EXPECTED_OUTPUT_CONTRACT,
    }
