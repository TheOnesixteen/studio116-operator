from __future__ import annotations

import json
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from adapters.base import worker_packet
from adapters.claude_code import intended_read_only_command as intended_claude_read_only_command
from adapters.codex import (
    intended_dry_run_command,
    live_docs_only_command,
    live_model_file_command,
    live_policy_file_command,
    live_scaffold_only_command,
    live_tests_only_command,
    run_live_docs_only,
    run_live_model_file as run_codex_live_model_file,
    run_live_policy_file as run_codex_live_policy_file,
    run_live_scaffold_only,
    run_live_tests_only,
)
from adapters.gemini_cli import intended_review_command as intended_gemini_review_command
from app.artifact_store import write_json_artifact
from app.artifact_store import write_text_artifact
from app.config import get_settings
from app.db import transaction
from app.events import record_event, utc_now
from app.locks import active_locks, managed_lock
from app.models import HEALTH_STATUSES, TASK_STATES
from app.policies import (
    LIVE_CODEX_DOCS_ONLY_MODE,
    LIVE_CODEX_DOCS_ONLY_TARGETS,
    LIVE_CODEX_MODEL_FILE_ONLY_MODE,
    LIVE_CODEX_MODEL_FILE_ONLY_TARGETS,
    LIVE_CODEX_POLICY_FILE_ONLY_MODE,
    LIVE_CODEX_POLICY_FILE_ONLY_TARGETS,
    LIVE_CODEX_SCAFFOLD_ONLY_MODE,
    LIVE_CODEX_SCAFFOLD_ONLY_TARGETS,
    LIVE_CODEX_TESTS_ONLY_MODE,
    LIVE_CODEX_TESTS_ONLY_TARGETS,
    LIVE_CODEX_TIMEOUT_SECONDS,
    live_codex_allowed_targets_for_mode,
    live_codex_docs_only_allowed_targets_for_project,
    live_codex_docs_only_project_max_changed_files,
    live_codex_model_file_preflight_checks,
    live_codex_policy_file_preflight_checks,
    live_codex_preflight_checks,
    live_codex_scaffold_only_preflight_checks,
    live_codex_tests_only_preflight_checks,
    validate_live_codex_paths_for_mode,
    validate_live_codex_changed_files_for_mode,
    validate_live_codex_model_file_content,
    validate_live_codex_policy_file_content,
    validate_live_codex_tests_only_content,
)
from app.project_registry import get_project, preflight_project_write
from app.state_manager import assert_transition, validate_status
from tools.git_tools import (
    create_worktree,
    delegated_branch_name,
    delegated_worktree_path,
    git_apply_check,
    git_apply_patch,
    git_changed_files,
    git_diff,
    git_diff_against_ref,
    git_head,
    git_restore_path,
    git_reverse_diff,
    slugify,
)
from tools.caddy_tools import inspect_caddy
from tools.docker_tools import inspect_docker_health
from tools.systemd_tools import inspect_service


HEALTH_CHECK_TITLE = "Inspect Caddy, kairoke.service, and Docker health"
HEALTH_CHECK_GOAL = "Read-only inspection of Caddy, kairoke.service, and Docker health"
INBOX_STALE_AFTER_DAYS = 3
INBOX_UNRESOLVED_STATUSES = {"queued", "running", "review", "failed"}


def create_task(
    *,
    project: str,
    title: str,
    goal: str,
    task_type: str | None = None,
    priority: str = "medium",
    requested_by: str = "Rusty",
    constraints: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    routing: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    task_id = str(uuid.uuid4())
    now = utc_now()
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO tasks (
              id, project, title, goal, type, priority, status, requested_by,
              constraints_json, acceptance_criteria_json, routing_json,
              dependencies_json, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                project,
                title,
                goal,
                task_type,
                priority,
                requested_by,
                json.dumps(constraints or ["Phase 1 read-only and non-destructive"]),
                json.dumps(acceptance_criteria or []),
                json.dumps(routing or {}, sort_keys=True),
                "[]",
                json.dumps(metadata or {}, sort_keys=True),
                now,
                now,
            ),
        )
    record_event("task_created", f"Created task: {title}", task_id=task_id)
    transition_task(task_id, "queued", message="Task queued for Phase 1 scheduler")
    return task_id


def transition_task(task_id: str, to_status: str, *, message: str | None = None) -> None:
    validate_status(to_status)
    with transaction() as conn:
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise ValueError(f"Task not found: {task_id}")
        from_status = row["status"]
        assert_transition(from_status, to_status)
        fields = "status = ?, updated_at = ?"
        values: list[Any] = [to_status, utc_now()]
        if to_status == "running":
            fields += ", started_at = COALESCE(started_at, ?)"
            values.append(utc_now())
        if to_status in {"done", "failed", "canceled"}:
            fields += ", completed_at = ?"
            values.append(utc_now())
        values.append(task_id)
        conn.execute(f"UPDATE tasks SET {fields} WHERE id = ?", values)
    record_event(
        "task_transition",
        message or f"Task moved {from_status} -> {to_status}",
        task_id=task_id,
        metadata={"from": from_status, "to": to_status},
    )


def list_tasks() -> list[dict[str, Any]]:
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT id, project, title, type, priority, status, created_at, updated_at
            FROM tasks
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def task_inbox() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    with transaction() as conn:
        task_rows = conn.execute(
            """
            SELECT id, project, title, type, priority, status, created_at, updated_at, started_at
            FROM tasks
            ORDER BY created_at DESC
            """
        ).fetchall()
        run_rows = conn.execute(
            """
            SELECT task_runs.*
            FROM task_runs
            JOIN (
              SELECT task_id, MAX(started_at) AS latest_started_at
              FROM task_runs
              GROUP BY task_id
            ) latest
              ON latest.task_id = task_runs.task_id
             AND latest.latest_started_at = task_runs.started_at
            ORDER BY task_runs.started_at DESC
            """
        ).fetchall()
        artifact_rows = conn.execute(
            """
            SELECT task_artifacts.*
            FROM task_artifacts
            WHERE artifact_type IN ('changed_files', 'review_summary')
            ORDER BY created_at DESC
            """
        ).fetchall()

    tasks = [dict(row) for row in task_rows]
    latest_runs: dict[str, dict[str, Any]] = {}
    for row in run_rows:
        run = dict(row)
        latest_runs.setdefault(run["task_id"], run)

    latest_artifacts: dict[str, list[dict[str, Any]]] = {}
    for row in artifact_rows:
        artifact = dict(row)
        latest_artifacts.setdefault(artifact["task_id"], []).append(artifact)

    counts: dict[str, int] = {status: 0 for status in TASK_STATES}
    for task in tasks:
        counts[task["status"]] = counts.get(task["status"], 0) + 1

    enriched = []
    for task in tasks:
        latest_run = latest_runs.get(task["id"])
        age_days = _inbox_age_days(task.get("updated_at"), now)
        item = {
            **task,
            "latest_run": latest_run,
            "changed_files": _inbox_changed_files(latest_artifacts.get(task["id"], [])),
            "age_days": age_days,
            "is_stale": age_days >= INBOX_STALE_AFTER_DAYS,
        }
        enriched.append(item)

    unresolved = [task for task in enriched if task["status"] in INBOX_UNRESOLVED_STATUSES]

    return {
        "task_count": len(tasks),
        "counts": counts,
        "stale_after_days": INBOX_STALE_AFTER_DAYS,
        "current_unresolved": [task for task in unresolved if not task["is_stale"]],
        "stale_unresolved": [task for task in unresolved if task["is_stale"]],
        "review": [task for task in enriched if task["status"] == "review"],
        "failed": [task for task in enriched if task["status"] == "failed"],
        "running": [task for task in enriched if task["status"] == "running"],
        "queued": [task for task in enriched if task["status"] == "queued"],
        "active_locks": active_locks(),
    }


def _inbox_age_days(timestamp: str | None, now: datetime) -> int:
    if not timestamp:
        return 0
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age = now - parsed
    return max(age.days, 0)


def _inbox_changed_files(artifacts: list[dict[str, Any]]) -> list[str] | None:
    for artifact in artifacts:
        path = Path(artifact["path"])
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        changed_files = data.get("changed_files")
        if isinstance(changed_files, list) and all(isinstance(item, str) for item in changed_files):
            return changed_files
    return None


def show_task(task_id: str) -> dict[str, Any]:
    with transaction() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        runs = conn.execute(
            "SELECT * FROM task_runs WHERE task_id = ? ORDER BY started_at DESC",
            (task_id,),
        ).fetchall()
        artifacts = conn.execute(
            "SELECT * FROM task_artifacts WHERE task_id = ? ORDER BY created_at DESC",
            (task_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM events WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
        worker_executions = conn.execute(
            """
            SELECT worker_executions.*
            FROM worker_executions
            JOIN task_runs ON task_runs.id = worker_executions.run_id
            WHERE task_runs.task_id = ?
            ORDER BY worker_executions.started_at ASC
            """,
            (task_id,),
        ).fetchall()
    return {
        "task": dict(task),
        "runs": [dict(row) for row in runs],
        "artifacts": [dict(row) for row in artifacts],
        "events": [dict(row) for row in events],
        "worker_executions": [dict(row) for row in worker_executions],
    }


def next_queued_task() -> dict[str, Any] | None:
    with transaction() as conn:
        row = conn.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'queued'
            ORDER BY
              CASE priority
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
              END,
              created_at ASC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def get_task(task_id: str) -> dict[str, Any] | None:
    with transaction() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return dict(row) if row else None


def create_run(task_id: str, *, worker_name: str, run_type: str) -> str:
    run_id = str(uuid.uuid4())
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO task_runs (
              id, task_id, worker_name, run_type, status, started_at, heartbeat_at, metadata_json
            ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?)
            """,
            (run_id, task_id, worker_name, run_type, utc_now(), utc_now(), "{}"),
        )
    record_event("run_started", f"Started {run_type} with {worker_name}", task_id=task_id, run_id=run_id)
    return run_id


def update_run_workspace(run_id: str, *, worktree_path: str | None, branch_name: str | None) -> None:
    with transaction() as conn:
        conn.execute(
            """
            UPDATE task_runs
            SET worktree_path = ?, branch_name = ?, heartbeat_at = ?
            WHERE id = ?
            """,
            (worktree_path, branch_name, utc_now(), run_id),
        )


def finish_run(run_id: str, *, task_id: str, status: str, exit_code: int, summary: str) -> None:
    with transaction() as conn:
        conn.execute(
            """
            UPDATE task_runs
            SET status = ?, completed_at = ?, heartbeat_at = ?, exit_code = ?, summary = ?
            WHERE id = ?
            """,
            (status, utc_now(), utc_now(), exit_code, summary, run_id),
        )
    record_event("run_finished", summary, task_id=task_id, run_id=run_id, metadata={"status": status})


def record_worker_execution(run_id: str, worker_name: str, result) -> None:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO worker_executions (
              id, run_id, worker_name, command, stdout, stderr, exit_code,
              started_at, completed_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                run_id,
                worker_name,
                result.command,
                result.stdout,
                result.stderr,
                result.exit_code,
                utc_now(),
                utc_now(),
                json.dumps({"timed_out": result.timed_out}, sort_keys=True),
            ),
        )


def record_intended_worker_command(
    *,
    run_id: str,
    worker_name: str,
    command: list[str],
    stdin_summary: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO worker_executions (
              id, run_id, worker_name, command, stdin_summary, stdout, stderr, exit_code,
              started_at, completed_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                run_id,
                worker_name,
                " ".join(command),
                stdin_summary,
                "",
                "",
                None,
                utc_now(),
                utc_now(),
                json.dumps(metadata or {}, sort_keys=True),
            ),
        )


def approve_task(task_id: str) -> dict[str, Any]:
    task = get_task(task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")
    if task["status"] != "review":
        raise ValueError(f"Task must be in review to approve; current status is {task['status']}")
    run = _latest_review_run(task_id)
    _assert_phase22_review_task(task, run)
    with _review_action_locks(task, run):
        try:
            result = _promote_live_codex_docs_only(task, run)
        except Exception as exc:
            record_event(
                "promotion_failed",
                f"Approved diff promotion failed; task remains in review: {exc}",
                task_id=task_id,
                run_id=run["id"],
                level="warning",
            )
            raise
    approved_message = f"Rusty approved and promoted the {_reviewed_diff_description(task)}"
    transition_task(task_id, "done", message=approved_message)
    record_event(
        "task_approved",
        approved_message,
        task_id=task_id,
        run_id=run["id"],
        metadata={"promotion_summary_path": result["promotion_summary_path"]},
    )
    return {
        "task_id": task_id,
        "status": "done",
        "approved": True,
        "promoted": True,
        "worktree_preserved": True,
        **result,
    }


def reject_task(task_id: str) -> dict[str, Any]:
    task = get_task(task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")
    if task["status"] != "review":
        raise ValueError(f"Task must be in review to reject; current status is {task['status']}")
    run = _latest_review_run(task_id)
    _assert_phase22_review_task(task, run)
    with _review_action_locks(task, run):
        try:
            result = _discard_live_codex_docs_only(task, run)
        except Exception as exc:
            record_event(
                "discard_failed",
                f"Rejected diff discard failed; task remains in review: {exc}",
                task_id=task_id,
                run_id=run["id"],
                level="warning",
            )
            raise
    rejected_message = f"Rusty rejected and discarded the {_reviewed_diff_description(task)}"
    transition_task(task_id, "canceled", message=rejected_message)
    record_event(
        "task_rejected",
        rejected_message,
        task_id=task_id,
        run_id=run["id"],
        metadata={"discard_summary_path": result["discard_summary_path"]},
    )
    return {
        "task_id": task_id,
        "status": "canceled",
        "rejected": True,
        "discarded": True,
        "worktree_preserved": True,
        **result,
    }


def _latest_review_run(task_id: str) -> dict[str, Any]:
    with transaction() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM task_runs
            WHERE task_id = ?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
    if not row:
        raise ValueError(f"No run found for task: {task_id}")
    return dict(row)


def _assert_phase22_review_task(task: dict[str, Any], run: dict[str, Any]) -> None:
    routing = _task_json(task, "routing_json", {})
    mode = routing.get("delegation_mode")
    if mode == LIVE_CODEX_MODEL_FILE_ONLY_MODE:
        default_targets = LIVE_CODEX_MODEL_FILE_ONLY_TARGETS
    elif mode == LIVE_CODEX_POLICY_FILE_ONLY_MODE:
        default_targets = LIVE_CODEX_POLICY_FILE_ONLY_TARGETS
    elif mode == LIVE_CODEX_SCAFFOLD_ONLY_MODE:
        default_targets = LIVE_CODEX_SCAFFOLD_ONLY_TARGETS
    elif mode == LIVE_CODEX_TESTS_ONLY_MODE:
        default_targets = LIVE_CODEX_TESTS_ONLY_TARGETS
    else:
        default_targets = LIVE_CODEX_DOCS_ONLY_TARGETS
    target_paths = routing.get("target_paths") or routing.get("targets") or default_targets
    if isinstance(target_paths, str):
        target_paths = [target_paths]
    canonical_repo_path_for_task(task)
    if task["type"] != "delegated":
        raise PermissionError("Phase 2.2 review loop is limited to delegated tasks")
    if routing.get("worker") != "codex":
        raise PermissionError("Phase 2.2 review loop is limited to worker=codex")
    if mode not in {
        LIVE_CODEX_DOCS_ONLY_MODE,
        LIVE_CODEX_TESTS_ONLY_MODE,
        LIVE_CODEX_POLICY_FILE_ONLY_MODE,
        LIVE_CODEX_MODEL_FILE_ONLY_MODE,
        LIVE_CODEX_SCAFFOLD_ONLY_MODE,
    }:
        raise PermissionError("Phase 2.2 review loop is limited to approved live Codex modes")
    if not all(
        check["passed"]
        for check in validate_live_codex_paths_for_mode(
            mode,
            target_paths,
            project=task["project"],
            worker=routing.get("worker", "codex"),
        )
    ):
        raise PermissionError("Phase 2 review loop is limited to policy-whitelisted live Codex targets")
    if run["worker_name"] != "codex" or run["run_type"] != f"delegated_{mode}":
        raise PermissionError("Phase 2 review loop requires a matching live Codex run")
    if not run["worktree_path"]:
        raise ValueError("Phase 2.2 review loop requires a preserved worktree")


@contextmanager
def _review_action_locks(task: dict[str, Any], run: dict[str, Any]) -> Iterator[None]:
    repo_path = canonical_repo_path_for_task(task)
    stack = ExitStack()
    try:
        stack.enter_context(
            managed_lock(
                lock_type="scheduler",
                resource_key=f"review:{task['id']}",
                task_id=task["id"],
                run_id=run["id"],
                worker_name="scheduler",
                metadata={"phase": "2.2", "action": "review_loop"},
            )
        )
        stack.enter_context(
            managed_lock(
                lock_type="delegated_writer",
                resource_key="codex",
                task_id=task["id"],
                run_id=run["id"],
                worker_name="scheduler",
                metadata={"phase": "2.2"},
            )
        )
        stack.enter_context(
            managed_lock(
                lock_type="repo",
                resource_key=str(repo_path),
                task_id=task["id"],
                run_id=run["id"],
                worker_name="scheduler",
                metadata={"phase": "2.2"},
            )
        )
        stack.enter_context(
            managed_lock(
                lock_type="worktree",
                resource_key=str(run["worktree_path"]),
                task_id=task["id"],
                run_id=run["id"],
                worker_name="scheduler",
                metadata={"phase": "2.2"},
            )
        )
        yield
    finally:
        stack.close()


def _worktree_path_for_review(run: dict[str, Any]) -> Path:
    worktree_path = Path(run["worktree_path"]).resolve()
    runtime_worktrees = get_settings().worktrees_dir.resolve()
    if runtime_worktrees not in [worktree_path, *worktree_path.parents]:
        raise PermissionError("Phase 2.2 review worktree must be under runtime/worktrees")
    return worktree_path


def canonical_repo_path_for_task(task: dict[str, Any]) -> Path:
    if task["project"] == "operator":
        return get_settings().repo_root
    try:
        return Path(get_project(task["project"])["repo_path"])
    except KeyError as exc:
        raise PermissionError(f"Review loop requires a known project: {task['project']}") from exc


def _changed_files_from_result(result) -> list[str]:
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _live_codex_mode_for_task(task: dict[str, Any]) -> str:
    routing = _task_json(task, "routing_json", {})
    return routing.get("delegation_mode") or LIVE_CODEX_DOCS_ONLY_MODE


def _live_codex_mode_label_for_task(task: dict[str, Any]) -> str:
    mode = _live_codex_mode_for_task(task)
    if mode == LIVE_CODEX_MODEL_FILE_ONLY_MODE:
        return "model-file"
    if mode == LIVE_CODEX_POLICY_FILE_ONLY_MODE:
        return "policy-file"
    if mode == LIVE_CODEX_SCAFFOLD_ONLY_MODE:
        return "scaffold"
    if mode == LIVE_CODEX_TESTS_ONLY_MODE:
        return "tests-only"
    return "docs-only"


def _reviewed_diff_description(task: dict[str, Any]) -> str:
    return f"reviewed Codex {_live_codex_mode_label_for_task(task)} diff"


def _phase22_changed_file_checks(task: dict[str, Any], changed_files: list[str], mode: str) -> tuple[list[dict], bool]:
    routing = _task_json(task, "routing_json", {})
    checks = validate_live_codex_changed_files_for_mode(
        mode,
        changed_files,
        project=task["project"],
        worker=routing.get("worker", "codex"),
    )
    passed = all(check["passed"] for check in checks)
    return checks, passed


def _live_codex_content_checks(
    worktree_path: Path,
    changed_files: list[str],
    mode: str,
    *,
    project: str = "operator",
) -> list[dict]:
    if mode == LIVE_CODEX_MODEL_FILE_ONLY_MODE:
        if project != "operator":
            return []
        return validate_live_codex_model_file_content(worktree_path, changed_files)
    if mode == LIVE_CODEX_POLICY_FILE_ONLY_MODE:
        return validate_live_codex_policy_file_content(worktree_path, changed_files)
    if mode == LIVE_CODEX_TESTS_ONLY_MODE:
        return validate_live_codex_tests_only_content(worktree_path, changed_files)
    return []


def _write_promotion_preflight(
    *,
    task: dict[str, Any],
    run: dict[str, Any],
    worktree_path: Path,
    changed_files: list[str],
    checks: list[dict],
    apply_check_result=None,
    passed: bool,
    summary: str,
    recommended_next_action: str | None = None,
    stale_patch_recovery: dict[str, Any] | None = None,
) -> Path:
    preflight_checks = [
        {"name": "task_status_is_review", "passed": task["status"] == "review"},
        {"name": "project_is_operator_or_known_writable", "passed": bool(canonical_repo_path_for_task(task))},
        {"name": "worker_is_codex", "passed": run["worker_name"] == "codex"},
        {
            "name": "mode_is_approved_live_codex_mode",
            "passed": run["run_type"]
            in {
                f"delegated_{LIVE_CODEX_DOCS_ONLY_MODE}",
                f"delegated_{LIVE_CODEX_TESTS_ONLY_MODE}",
                f"delegated_{LIVE_CODEX_POLICY_FILE_ONLY_MODE}",
                f"delegated_{LIVE_CODEX_MODEL_FILE_ONLY_MODE}",
                f"delegated_{LIVE_CODEX_SCAFFOLD_ONLY_MODE}",
            },
        },
        {"name": "worktree_under_runtime_worktrees", "passed": True},
        *checks,
    ]
    if apply_check_result is not None:
        preflight_checks.append(
            {
                "name": "canonical_git_apply_check",
                "passed": apply_check_result.exit_code == 0,
                "details": {
                    "command": apply_check_result.command,
                    "exit_code": apply_check_result.exit_code,
                    "stdout": apply_check_result.stdout,
                    "stderr": apply_check_result.stderr,
                },
            }
        )
    return write_json_artifact(
        task_id=task["id"],
        run_id=run["id"],
        artifact_type="promotion_preflight",
        label="Live Codex promotion preflight",
        filename="promotion_preflight.json",
        data={
            "summary": summary,
            "recommended_next_action": recommended_next_action,
            "passed": passed,
            "changed_files": changed_files,
            "checks": preflight_checks,
            "allowed_targets": (
                live_codex_docs_only_allowed_targets_for_project(
                    task["project"],
                    _task_json(task, "routing_json", {}).get("worker", "codex"),
                )
                if _live_codex_mode_for_task(task) == LIVE_CODEX_DOCS_ONLY_MODE
                else LIVE_CODEX_SCAFFOLD_ONLY_TARGETS
                if _live_codex_mode_for_task(task) == LIVE_CODEX_MODEL_FILE_ONLY_MODE
                and task["project"] != "operator"
                else live_codex_allowed_targets_for_mode(_live_codex_mode_for_task(task))
            ),
            "worktree_path": str(worktree_path),
            "canonical_repo_path": str(canonical_repo_path_for_task(task)),
            "stale_patch_recovery": stale_patch_recovery,
        },
    )


def _live_codex_stale_patch_recovery(
    *,
    canonical_repo_path: Path,
    run: dict[str, Any],
    worktree_path: Path,
    changed_files: list[str],
    apply_check_result,
) -> dict[str, Any]:
    review_head_result = git_head(worktree_path=worktree_path)
    record_worker_execution(run["id"], "shell_ops", review_head_result)
    canonical_head_result = git_head(worktree_path=canonical_repo_path)
    record_worker_execution(run["id"], "shell_ops", canonical_head_result)

    canonical_target_diff_result = None
    if review_head_result.exit_code == 0 and changed_files:
        canonical_target_diff_result = git_diff_against_ref(
            repo_path=canonical_repo_path,
            base_ref=review_head_result.stdout.strip(),
            target_paths=changed_files,
        )
        record_worker_execution(run["id"], "shell_ops", canonical_target_diff_result)

    target_file_drifted = (
        canonical_target_diff_result is not None
        and canonical_target_diff_result.exit_code == 0
        and bool(canonical_target_diff_result.stdout.strip())
    )
    return {
        "reason": "approved_patch_no_longer_applies_cleanly",
        "target_paths": changed_files,
        "target_file_drifted_since_review_started": target_file_drifted,
        "review_head": {
            "command": review_head_result.command,
            "exit_code": review_head_result.exit_code,
            "stdout": review_head_result.stdout,
            "stderr": review_head_result.stderr,
        },
        "canonical_head": {
            "command": canonical_head_result.command,
            "exit_code": canonical_head_result.exit_code,
            "stdout": canonical_head_result.stdout,
            "stderr": canonical_head_result.stderr,
        },
        "apply_check": {
            "command": apply_check_result.command,
            "exit_code": apply_check_result.exit_code,
            "stdout": apply_check_result.stdout,
            "stderr": apply_check_result.stderr,
        },
        "canonical_target_diff": None
        if canonical_target_diff_result is None
        else {
            "command": canonical_target_diff_result.command,
            "exit_code": canonical_target_diff_result.exit_code,
            "stdout": canonical_target_diff_result.stdout,
            "stderr": canonical_target_diff_result.stderr,
        },
        "forced_apply": False,
        "auto_merge": False,
        "canonical_overwrite": False,
    }


def _promote_live_codex_docs_only(task: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    worktree_path = _worktree_path_for_review(run)
    canonical_repo_path = canonical_repo_path_for_task(task)
    diff_result = git_diff(worktree_path=worktree_path)
    record_worker_execution(run["id"], "shell_ops", diff_result)
    changed_result = git_changed_files(worktree_path=worktree_path)
    record_worker_execution(run["id"], "shell_ops", changed_result)
    changed_files = _changed_files_from_result(changed_result)
    mode = _live_codex_mode_for_task(task)
    mode_label = _live_codex_mode_label_for_task(task)
    stale_recovery_modes = {
        LIVE_CODEX_TESTS_ONLY_MODE,
        LIVE_CODEX_POLICY_FILE_ONLY_MODE,
        LIVE_CODEX_MODEL_FILE_ONLY_MODE,
        LIVE_CODEX_SCAFFOLD_ONLY_MODE,
    }
    checks, changed_files_passed = _phase22_changed_file_checks(task, changed_files, mode)
    content_checks = _live_codex_content_checks(worktree_path, changed_files, mode, project=task["project"])
    checks = [*checks, *content_checks]
    content_checks_passed = all(check["passed"] for check in content_checks)
    if diff_result.exit_code != 0 or changed_result.exit_code != 0 or not changed_files_passed or not content_checks_passed:
        preflight_path = _write_promotion_preflight(
            task=task,
            run=run,
            worktree_path=worktree_path,
            changed_files=changed_files,
            checks=checks,
            passed=False,
            summary="Live Codex promotion preflight failed before patch apply check",
        )
        raise RuntimeError(f"Live Codex promotion preflight failed; task remains in review: {preflight_path}")

    approved_patch_path = write_text_artifact(
        task_id=task["id"],
        run_id=run["id"],
        artifact_type="approved_patch",
        label=f"Live Codex approved {mode_label} patch",
        filename="approved_patch.patch",
        content=diff_result.stdout,
    )
    rollback_result = git_reverse_diff(worktree_path=worktree_path)
    record_worker_execution(run["id"], "shell_ops", rollback_result)
    if rollback_result.exit_code != 0:
        preflight_path = _write_promotion_preflight(
            task=task,
            run=run,
            worktree_path=worktree_path,
            changed_files=changed_files,
            checks=checks,
            passed=False,
            summary="Live Codex promotion preflight failed while generating rollback patch",
        )
        raise RuntimeError(f"Failed to generate rollback patch; task remains in review: {preflight_path}")
    rollback_patch_path = write_text_artifact(
        task_id=task["id"],
        run_id=run["id"],
        artifact_type="rollback_patch",
        label=f"Live Codex rollback patch for promoted {mode_label} diff",
        filename="rollback_patch.patch",
        content=rollback_result.stdout,
    )
    apply_check_result = git_apply_check(repo_path=canonical_repo_path, patch_path=approved_patch_path)
    record_worker_execution(run["id"], "shell_ops", apply_check_result)
    if apply_check_result.exit_code != 0:
        recommended_next_action = (
            f"Reject this stale {mode_label} review, inspect the canonical target changes, "
            f"and create a fresh {mode} task if the change is still wanted."
        )
        stale_patch_recovery = (
            _live_codex_stale_patch_recovery(
                canonical_repo_path=canonical_repo_path,
                run=run,
                worktree_path=worktree_path,
                changed_files=changed_files,
                apply_check_result=apply_check_result,
            )
            if mode in stale_recovery_modes
            else None
        )
        preflight_path = _write_promotion_preflight(
            task=task,
            run=run,
            worktree_path=worktree_path,
            changed_files=changed_files,
            checks=checks,
            apply_check_result=apply_check_result,
            passed=False,
            summary=(
                f"Live Codex {mode_label} promotion blocked because the approved patch no longer applies cleanly. "
                f"Task remains in review; no force apply, auto-merge, or canonical overwrite was attempted."
            ),
            recommended_next_action=recommended_next_action
            if mode in stale_recovery_modes
            else None,
            stale_patch_recovery=stale_patch_recovery,
        )
        raise RuntimeError(f"Approved patch no longer applies cleanly; task remains in review: {preflight_path}")

    promotion_preflight_path = _write_promotion_preflight(
        task=task,
        run=run,
        worktree_path=worktree_path,
        changed_files=changed_files,
        checks=checks,
        apply_check_result=apply_check_result,
        passed=True,
        summary="Live Codex promotion preflight passed",
    )
    canonical_head_before = git_head(worktree_path=canonical_repo_path)
    record_worker_execution(run["id"], "shell_ops", canonical_head_before)
    apply_result = git_apply_patch(repo_path=canonical_repo_path, patch_path=approved_patch_path)
    record_worker_execution(run["id"], "shell_ops", apply_result)
    if apply_result.exit_code != 0:
        write_json_artifact(
            task_id=task["id"],
            run_id=run["id"],
            artifact_type="promotion_summary",
            label="Live Codex failed promotion summary",
            filename="promotion_summary.json",
            data={
                "summary": f"Approved {mode_label} patch apply failed after a successful apply check; task remains in review",
                "promoted": False,
                "changed_files": changed_files,
                "canonical_repo_path": str(canonical_repo_path),
                "worktree_path": str(worktree_path),
                "branch_name": run["branch_name"],
                "promotion_preflight_path": str(promotion_preflight_path),
                "approved_patch_path": str(approved_patch_path),
                "rollback_patch_path": str(rollback_patch_path),
                "apply": {
                    "command": apply_result.command,
                    "exit_code": apply_result.exit_code,
                    "stdout": apply_result.stdout,
                    "stderr": apply_result.stderr,
                },
                "commit_created": False,
                "merged": False,
                "pushed": False,
                "worktree_preserved": True,
            },
        )
        raise RuntimeError("Approved patch apply failed after a successful apply check; task remains in review")
    canonical_head_after = git_head(worktree_path=canonical_repo_path)
    record_worker_execution(run["id"], "shell_ops", canonical_head_after)
    promotion_summary_path = write_json_artifact(
        task_id=task["id"],
        run_id=run["id"],
        artifact_type="promotion_summary",
        label="Live Codex promotion summary",
        filename="promotion_summary.json",
        data={
            "summary": f"Approved {mode_label} diff promoted to the canonical working tree without commit, merge, or push",
            "promoted": True,
            "changed_files": changed_files,
            "canonical_repo_path": str(canonical_repo_path),
            "worktree_path": str(worktree_path),
            "branch_name": run["branch_name"],
            "promotion_preflight_path": str(promotion_preflight_path),
            "approved_patch_path": str(approved_patch_path),
            "rollback_patch_path": str(rollback_patch_path),
            "canonical_head_before": canonical_head_before.stdout.strip(),
            "canonical_head_after": canonical_head_after.stdout.strip(),
            "commit_created": False,
            "merged": False,
            "pushed": False,
            "worktree_preserved": True,
        },
    )
    record_event(
        "promotion_succeeded",
        f"Promoted approved {mode_label} diff to canonical working tree without commit, merge, or push",
        task_id=task["id"],
        run_id=run["id"],
        metadata={"promotion_summary_path": str(promotion_summary_path)},
    )
    return {
        "promotion_preflight_path": str(promotion_preflight_path),
        "approved_patch_path": str(approved_patch_path),
        "rollback_patch_path": str(rollback_patch_path),
        "promotion_summary_path": str(promotion_summary_path),
    }


def _discard_live_codex_docs_only(task: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    worktree_path = _worktree_path_for_review(run)
    diff_result = git_diff(worktree_path=worktree_path)
    record_worker_execution(run["id"], "shell_ops", diff_result)
    changed_result = git_changed_files(worktree_path=worktree_path)
    record_worker_execution(run["id"], "shell_ops", changed_result)
    changed_files = _changed_files_from_result(changed_result)
    mode = _live_codex_mode_for_task(task)
    mode_label = _live_codex_mode_label_for_task(task)
    checks, changed_files_passed = _phase22_changed_file_checks(task, changed_files, mode)
    rejected_patch_path = write_text_artifact(
        task_id=task["id"],
        run_id=run["id"],
        artifact_type="rejected_patch",
        label=f"Live Codex rejected {mode_label} patch",
        filename="rejected_patch.patch",
        content=diff_result.stdout,
    )
    if diff_result.exit_code != 0 or changed_result.exit_code != 0 or not changed_files_passed:
        discard_summary_path = write_json_artifact(
            task_id=task["id"],
            run_id=run["id"],
            artifact_type="discard_summary",
            label="Live Codex discard summary",
            filename="discard_summary.json",
            data={
                "summary": "Rejected diff discard failed before restore because changed files were not policy-whitelisted targets",
                "discarded": False,
                "changed_files": changed_files,
                "checks": checks,
                "rejected_patch_path": str(rejected_patch_path),
                "worktree_path": str(worktree_path),
                "canonical_repo_touched": False,
            },
        )
        raise RuntimeError(f"Live Codex discard preflight failed; task remains in review: {discard_summary_path}")

    restore_results = []
    for changed_file in changed_files:
        restore_result = git_restore_path(worktree_path=worktree_path, target_path=changed_file)
        restore_results.append(restore_result)
        record_worker_execution(run["id"], "shell_ops", restore_result)
    failed_restore = next((result for result in restore_results if result.exit_code != 0), None)
    if failed_restore:
        discard_summary_path = write_json_artifact(
            task_id=task["id"],
            run_id=run["id"],
            artifact_type="discard_summary",
            label="Live Codex discard summary",
            filename="discard_summary.json",
            data={
                "summary": f"Rejected {mode_label} diff discard failed during git restore",
                "discarded": False,
                "changed_files": changed_files,
                "checks": checks,
                "restore": {
                    "command": failed_restore.command,
                    "exit_code": failed_restore.exit_code,
                    "stdout": failed_restore.stdout,
                    "stderr": failed_restore.stderr,
                },
                "rejected_patch_path": str(rejected_patch_path),
                "worktree_path": str(worktree_path),
                "canonical_repo_touched": False,
            },
        )
        raise RuntimeError(f"Live Codex discard failed; task remains in review: {discard_summary_path}")

    discard_summary_path = write_json_artifact(
        task_id=task["id"],
        run_id=run["id"],
        artifact_type="discard_summary",
        label="Live Codex discard summary",
        filename="discard_summary.json",
        data={
            "summary": f"Rejected {mode_label} diff discarded from delegated worktree; artifacts and worktree preserved",
            "discarded": True,
            "changed_files": changed_files,
            "checks": checks,
            "restore": [
                {
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
                for result in restore_results
            ],
            "rejected_patch_path": str(rejected_patch_path),
            "worktree_path": str(worktree_path),
            "canonical_repo_touched": False,
            "worktree_preserved": True,
        },
    )
    record_event(
        "discard_succeeded",
        f"Rejected {mode_label} diff discarded from delegated worktree; artifacts and worktree preserved",
        task_id=task["id"],
        run_id=run["id"],
        metadata={"discard_summary_path": str(discard_summary_path)},
    )
    return {
        "rejected_patch_path": str(rejected_patch_path),
        "discard_summary_path": str(discard_summary_path),
    }


def _task_json(task: dict[str, Any], key: str, default):
    raw = task.get(key)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def run_delegated_dry_run(task: dict[str, Any], run_id: str) -> dict[str, Any]:
    routing = _task_json(task, "routing_json", {})
    constraints = _task_json(task, "constraints_json", [])
    worker = routing.get("worker", "codex")
    delegation_mode = routing.get("delegation_mode", "dry_run")
    if delegation_mode != "dry_run":
        raise PermissionError("First Phase 2 slice supports delegated dry_run only")
    if worker not in {"codex", "claude_code", "gemini_cli"}:
        raise PermissionError(f"First Phase 2 slice does not support worker: {worker}")

    settings = get_settings()
    read_only = worker in {"claude_code", "gemini_cli"} or bool(routing.get("read_only"))
    allowed_actions = ["inspect_files", "read_logs"]
    branch_name = None
    worktree_path = None

    if worker == "codex":
        if task["project"] != "operator":
            raise PermissionError("First delegated Codex dry-run slice is limited to project=operator")
        read_only = False
        allowed_actions.extend(["create_worktrees", "create_branches", "draft_patches", "run_tests"])
        branch_name = delegated_branch_name(task_id=task["id"], worker=worker, title=task["title"])
        worktree_path = delegated_worktree_path(task_id=task["id"], worker=worker)
        result = create_worktree(repo_path=settings.repo_root, worktree_path=worktree_path, branch_name=branch_name)
        record_worker_execution(run_id, "shell_ops", result)
        if result.exit_code != 0:
            raise RuntimeError(f"Failed to create delegated worktree: {result.stderr or result.stdout}")
        update_run_workspace(run_id, worktree_path=str(worktree_path), branch_name=branch_name)
    else:
        read_only = True
        allowed_actions.append("delegate_read_only")
        update_run_workspace(run_id, worktree_path=None, branch_name=None)

    packet = worker_packet(
        worker=worker,
        task=task,
        run_id=run_id,
        mode="dry_run",
        allowed_actions=allowed_actions,
        constraints=constraints,
        branch_name=branch_name,
        worktree_path=worktree_path,
        read_only=read_only,
    )
    packet_path = write_json_artifact(
        task_id=task["id"],
        run_id=run_id,
        artifact_type="worker_packet",
        label=f"{worker} dry-run worker packet",
        data=packet,
    )
    if worker == "codex":
        intended_command = intended_dry_run_command(packet_path=packet_path, worktree_path=worktree_path)
    elif worker == "claude_code":
        intended_command = intended_claude_read_only_command(packet_path=packet_path)
    else:
        intended_command = intended_gemini_review_command(packet_path=packet_path)
    record_intended_worker_command(
        run_id=run_id,
        worker_name=worker,
        command=intended_command,
        stdin_summary=f"Dry-run packet artifact: {packet_path}",
        metadata={"dry_run": True, "launched": False, "packet_path": str(packet_path)},
    )
    summary = f"Delegated dry-run prepared for {worker}; intended command recorded but not launched"
    summary_path = write_json_artifact(
        task_id=task["id"],
        run_id=run_id,
        artifact_type="delegation_summary",
        label=f"{worker} dry-run delegation summary",
        data={
            "summary": summary,
            "worker": worker,
            "mode": "dry_run",
            "launched": False,
            "worktree_path": str(worktree_path) if worktree_path else None,
            "branch_name": branch_name,
            "packet_path": str(packet_path),
            "intended_command": intended_command,
        },
    )
    record_event(
        "delegation_dry_run_prepared",
        f"Prepared {worker} dry-run delegation packet: {packet_path}",
        task_id=task["id"],
        run_id=run_id,
        metadata={"summary_path": str(summary_path), "worker": worker},
    )
    return {
        "overall_status": "ok",
        "task_succeeded": True,
        "summary": summary,
        "key_findings": [summary],
    }


def _artifact_path_for(task_id: str, run_id: str, filename: str):
    return get_settings().artifacts_dir / task_id / run_id / filename


def _active_delegated_writer_count_excluding(run_id: str) -> int:
    with transaction() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM locks
            WHERE status = 'active'
              AND lock_type = 'delegated_writer'
              AND resource_key = 'codex'
              AND (run_id IS NULL OR run_id != ?)
            """,
            (run_id,),
        ).fetchone()
    return int(row["count"])


def run_live_codex_docs_only(task: dict[str, Any], run_id: str) -> dict[str, Any]:
    return _run_live_codex_policy_task(task, run_id, mode=LIVE_CODEX_DOCS_ONLY_MODE)


def run_live_codex_tests_only(task: dict[str, Any], run_id: str) -> dict[str, Any]:
    return _run_live_codex_policy_task(task, run_id, mode=LIVE_CODEX_TESTS_ONLY_MODE)


def run_live_codex_policy_file(task: dict[str, Any], run_id: str) -> dict[str, Any]:
    return _run_live_codex_policy_task(task, run_id, mode=LIVE_CODEX_POLICY_FILE_ONLY_MODE)


def run_live_codex_model_file(task: dict[str, Any], run_id: str) -> dict[str, Any]:
    return _run_live_codex_policy_task(task, run_id, mode=LIVE_CODEX_MODEL_FILE_ONLY_MODE)


def run_live_codex_scaffold_only(task: dict[str, Any], run_id: str) -> dict[str, Any]:
    return _run_live_codex_policy_task(task, run_id, mode=LIVE_CODEX_SCAFFOLD_ONLY_MODE)


def _run_live_codex_policy_task(task: dict[str, Any], run_id: str, *, mode: str) -> dict[str, Any]:
    routing = _task_json(task, "routing_json", {})
    constraints = _task_json(task, "constraints_json", [])
    worker = routing.get("worker")
    delegation_mode = routing.get("delegation_mode")
    if mode == LIVE_CODEX_MODEL_FILE_ONLY_MODE:
        default_targets = LIVE_CODEX_MODEL_FILE_ONLY_TARGETS
    elif mode == LIVE_CODEX_SCAFFOLD_ONLY_MODE:
        default_targets = LIVE_CODEX_SCAFFOLD_ONLY_TARGETS
    elif mode == LIVE_CODEX_POLICY_FILE_ONLY_MODE:
        default_targets = LIVE_CODEX_POLICY_FILE_ONLY_TARGETS
    elif mode == LIVE_CODEX_TESTS_ONLY_MODE:
        default_targets = LIVE_CODEX_TESTS_ONLY_TARGETS
    else:
        default_targets = LIVE_CODEX_DOCS_ONLY_TARGETS
    target_paths = routing.get("target_paths") or routing.get("targets") or default_targets
    if isinstance(target_paths, str):
        target_paths = [target_paths]

    settings = get_settings()
    repo_path = settings.repo_root
    external_repo_modes = {
        LIVE_CODEX_DOCS_ONLY_MODE,
        LIVE_CODEX_MODEL_FILE_ONLY_MODE,
        LIVE_CODEX_SCAFFOLD_ONLY_MODE,
    }
    use_external_repo = task["project"] != "operator" and mode in external_repo_modes
    if use_external_repo:
        try:
            repo_path = Path(get_project(task["project"])["repo_path"])
        except KeyError:
            repo_path = settings.repo_root
    if use_external_repo:
        branch_name = (
            f"operator-external-{slugify(task['project'])}-{task['id'].split('-')[0]}-"
            f"codex-{slugify(task['title'])}"
        )
    else:
        branch_name = delegated_branch_name(task_id=task["id"], worker="codex", title=task["title"])
    worktree_path = delegated_worktree_path(task_id=task["id"], worker="codex")
    worktree_result = create_worktree(repo_path=repo_path, worktree_path=worktree_path, branch_name=branch_name)
    record_worker_execution(run_id, "shell_ops", worktree_result)
    worktree_ready = worktree_result.exit_code == 0 or worktree_path.exists()
    update_run_workspace(run_id, worktree_path=str(worktree_path), branch_name=branch_name)

    packet_path = _artifact_path_for(task["id"], run_id, "worker_packet.json")
    if mode == LIVE_CODEX_MODEL_FILE_ONLY_MODE:
        intended_command = live_model_file_command(worktree_path=worktree_path, packet_path=packet_path)
        preflight_checks = live_codex_model_file_preflight_checks(
            project=task["project"],
            worker=worker,
            mode=delegation_mode,
            target_paths=target_paths,
            repo_root=repo_path,
            worktree_path=worktree_path,
            command_cwd=worktree_path,
            active_delegated_writer_locks=_active_delegated_writer_count_excluding(run_id),
            goal=task["goal"],
            constraints=constraints,
            worktree_ready=worktree_ready,
        )
        mode_label = "model-file"
    elif mode == LIVE_CODEX_SCAFFOLD_ONLY_MODE:
        intended_command = live_scaffold_only_command(worktree_path=worktree_path, packet_path=packet_path)
        preflight_checks = live_codex_scaffold_only_preflight_checks(
            project=task["project"],
            worker=worker,
            mode=delegation_mode,
            target_paths=target_paths,
            repo_root=repo_path,
            worktree_path=worktree_path,
            command_cwd=worktree_path,
            active_delegated_writer_locks=_active_delegated_writer_count_excluding(run_id),
            goal=task["goal"],
            constraints=constraints,
            worktree_ready=worktree_ready,
        )
        mode_label = "scaffold"
    elif mode == LIVE_CODEX_POLICY_FILE_ONLY_MODE:
        intended_command = live_policy_file_command(worktree_path=worktree_path, packet_path=packet_path)
        preflight_checks = live_codex_policy_file_preflight_checks(
            project=task["project"],
            worker=worker,
            mode=delegation_mode,
            target_paths=target_paths,
            repo_root=settings.repo_root,
            worktree_path=worktree_path,
            command_cwd=worktree_path,
            active_delegated_writer_locks=_active_delegated_writer_count_excluding(run_id),
            goal=task["goal"],
            constraints=constraints,
            worktree_ready=worktree_ready,
        )
        mode_label = "policy-file"
    elif mode == LIVE_CODEX_TESTS_ONLY_MODE:
        intended_command = live_tests_only_command(worktree_path=worktree_path, packet_path=packet_path)
        preflight_checks = live_codex_tests_only_preflight_checks(
            project=task["project"],
            worker=worker,
            mode=delegation_mode,
            target_paths=target_paths,
            repo_root=settings.repo_root,
            worktree_path=worktree_path,
            command_cwd=worktree_path,
            active_delegated_writer_locks=_active_delegated_writer_count_excluding(run_id),
            goal=task["goal"],
            constraints=constraints,
            worktree_ready=worktree_ready,
        )
        mode_label = "tests-only"
    else:
        intended_command = live_docs_only_command(worktree_path=worktree_path, packet_path=packet_path)
        preflight_checks = live_codex_preflight_checks(
            project=task["project"],
            worker=worker,
            mode=delegation_mode,
            target_paths=target_paths,
            repo_root=repo_path,
            worktree_path=worktree_path,
            command_cwd=worktree_path,
            active_delegated_writer_locks=_active_delegated_writer_count_excluding(run_id),
            goal=task["goal"],
            constraints=constraints,
            worktree_ready=worktree_ready,
        )
        mode_label = "docs-only"
    preflight_passed = all(check["passed"] for check in preflight_checks)
    allowed_targets = (
        live_codex_docs_only_allowed_targets_for_project(task["project"], worker or "")
        if mode == LIVE_CODEX_DOCS_ONLY_MODE
        else LIVE_CODEX_SCAFFOLD_ONLY_TARGETS
        if mode == LIVE_CODEX_MODEL_FILE_ONLY_MODE and task["project"] != "operator"
        else live_codex_allowed_targets_for_mode(mode)
    )
    write_json_artifact(
        task_id=task["id"],
        run_id=run_id,
        artifact_type="preflight_result",
        label=f"Live Codex {mode_label} preflight result",
        filename="preflight_result.json",
        data={
            "mode": mode,
            "passed": preflight_passed,
            "checks": preflight_checks,
            "target_paths": target_paths,
            "allowed_targets": allowed_targets,
            "timeout_seconds": LIVE_CODEX_TIMEOUT_SECONDS,
            "worktree_path": str(worktree_path),
            "branch_name": branch_name,
        },
    )
    if not preflight_passed:
        return {
            "overall_status": "failed",
            "task_succeeded": False,
            "summary": f"Live Codex {mode_label} preflight failed; Codex was not launched",
            "key_findings": [check["name"] for check in preflight_checks if not check["passed"]],
        }

    base_head_result = git_head(worktree_path=worktree_path)
    record_worker_execution(run_id, "shell_ops", base_head_result)
    packet = worker_packet(
        worker="codex",
        task=task,
        run_id=run_id,
        mode=mode,
        allowed_actions=["inspect_files", "draft_patches", "run_tests"],
        constraints=[
            *constraints,
            f"Live Codex {mode_label} slice",
            f"Modify only these target path(s): {', '.join(target_paths)}",
            "Do not install packages",
            "Do not use network-dependent work",
            "Do not commit, merge, or push",
        ],
        branch_name=branch_name,
        worktree_path=worktree_path,
        read_only=False,
    )
    write_json_artifact(
        task_id=task["id"],
        run_id=run_id,
        artifact_type="worker_packet",
        label=f"Codex live {mode_label} worker packet",
        filename="worker_packet.json",
        data={
            **packet,
            "target_paths": target_paths,
            "timeout_seconds": LIVE_CODEX_TIMEOUT_SECONDS,
            "allowed_targets": allowed_targets,
        },
    )

    if mode == LIVE_CODEX_MODEL_FILE_ONLY_MODE:
        codex_result = run_codex_live_model_file(
            worktree_path=worktree_path,
            packet_path=packet_path,
            timeout_seconds=LIVE_CODEX_TIMEOUT_SECONDS,
        )
    elif mode == LIVE_CODEX_SCAFFOLD_ONLY_MODE:
        codex_result = run_live_scaffold_only(
            worktree_path=worktree_path,
            packet_path=packet_path,
            timeout_seconds=LIVE_CODEX_TIMEOUT_SECONDS,
        )
    elif mode == LIVE_CODEX_POLICY_FILE_ONLY_MODE:
        codex_result = run_codex_live_policy_file(
            worktree_path=worktree_path,
            packet_path=packet_path,
            timeout_seconds=LIVE_CODEX_TIMEOUT_SECONDS,
        )
    elif mode == LIVE_CODEX_TESTS_ONLY_MODE:
        codex_result = run_live_tests_only(
            worktree_path=worktree_path,
            packet_path=packet_path,
            timeout_seconds=LIVE_CODEX_TIMEOUT_SECONDS,
        )
    else:
        codex_result = run_live_docs_only(
            worktree_path=worktree_path,
            packet_path=packet_path,
            timeout_seconds=LIVE_CODEX_TIMEOUT_SECONDS,
        )
    record_worker_execution(run_id, "codex", codex_result)
    write_json_artifact(
        task_id=task["id"],
        run_id=run_id,
        artifact_type="worker_result",
        label=f"Codex live {mode_label} worker result",
        filename="worker_result.json",
        data={
            "timed_out": codex_result.timed_out,
            "exit_code": codex_result.exit_code,
            "stdout": codex_result.stdout,
            "stderr": codex_result.stderr,
            "command": codex_result.command,
        },
    )
    if codex_result.timed_out:
        return {
            "overall_status": "failed",
            "task_succeeded": False,
            "summary": f"Live Codex {mode_label} execution timed out after 10 minutes",
            "key_findings": ["timeout_after_10_minutes", f"worktree preserved at {worktree_path}"],
        }
    if codex_result.exit_code != 0:
        return {
            "overall_status": "failed",
            "task_succeeded": False,
            "summary": f"Live Codex {mode_label} execution failed with exit code {codex_result.exit_code}",
            "key_findings": [codex_result.stderr or codex_result.stdout or "Codex returned nonzero exit code"],
        }

    diff_result = git_diff(worktree_path=worktree_path)
    record_worker_execution(run_id, "shell_ops", diff_result)
    changed_result = git_changed_files(worktree_path=worktree_path)
    record_worker_execution(run_id, "shell_ops", changed_result)
    current_head_result = git_head(worktree_path=worktree_path)
    record_worker_execution(run_id, "shell_ops", current_head_result)
    changed_files = [line.strip() for line in changed_result.stdout.splitlines() if line.strip()]
    no_changes_produced = not changed_files
    post_run_checks = validate_live_codex_changed_files_for_mode(
        mode,
        changed_files,
        project=task["project"],
        worker=worker or "",
    )
    post_run_checks.append(
        {
            "name": "codex_produced_changes",
            "passed": not no_changes_produced,
            "details": {"changed_files": changed_files},
        }
    )
    post_run_checks.extend(_live_codex_content_checks(worktree_path, changed_files, mode, project=task["project"]))
    if mode == LIVE_CODEX_DOCS_ONLY_MODE:
        project_max_changed_files = live_codex_docs_only_project_max_changed_files(task["project"], worker or "")
        post_run_checks.append(
            {
                "name": "changed_file_count_within_project_write_policy_max",
                "passed": len(changed_files) <= project_max_changed_files,
                "details": {"count": len(changed_files), "max": project_max_changed_files},
            }
        )
    elif mode == LIVE_CODEX_SCAFFOLD_ONLY_MODE and task["project"] != "operator":
        project_write = preflight_project_write(task["project"], worker=worker or "", lane="scaffold_only")
        project_max_changed_files = project_write.write_policy.get("max_changed_files")
        if isinstance(project_max_changed_files, int):
            post_run_checks.append(
                {
                    "name": "changed_file_count_within_project_write_policy_max",
                    "passed": len(changed_files) <= project_max_changed_files,
                    "details": {"count": len(changed_files), "max": project_max_changed_files},
                }
            )
    post_run_checks.append(
        {
            "name": "no_auto_commit_or_merge",
            "passed": base_head_result.exit_code == 0
            and current_head_result.exit_code == 0
            and base_head_result.stdout.strip() == current_head_result.stdout.strip(),
            "details": {
                "base_head": base_head_result.stdout.strip(),
                "current_head": current_head_result.stdout.strip(),
            },
        }
    )
    post_run_checks.append(
        {
            "name": "no_auto_push",
            "passed": True,
            "details": {"enforcement": "Codex packet forbids push; local post-run push detection is not available"},
        }
    )
    post_run_passed = diff_result.exit_code == 0 and changed_result.exit_code == 0 and all(
        check["passed"] for check in post_run_checks
    )
    write_text_artifact(
        task_id=task["id"],
        run_id=run_id,
        artifact_type="git_diff",
        label=f"Codex live {mode_label} git diff",
        filename="git_diff.patch",
        content=diff_result.stdout,
    )
    write_json_artifact(
        task_id=task["id"],
        run_id=run_id,
        artifact_type="changed_files",
        label=f"Codex live {mode_label} changed files",
        filename="changed_files.json",
        data={
            "changed_files": changed_files,
            "checks": post_run_checks,
            "passed": post_run_passed,
        },
    )
    review_summary = {
        "summary": f"Live Codex {mode_label} task is ready for Rusty review"
        if post_run_passed
        else f"Live Codex {mode_label} post-run validation failed",
        "requires_approval": True,
        "approval_required_before": ["merge", "commit", "push", "follow_on_action"],
        "task_stops_in": "review" if post_run_passed else "failed",
        "worktree_path": str(worktree_path),
        "branch_name": branch_name,
        "changed_files": changed_files,
        "post_run_checks": post_run_checks,
    }
    write_json_artifact(
        task_id=task["id"],
        run_id=run_id,
        artifact_type="review_summary",
        label=f"Codex live {mode_label} review summary",
        filename="review_summary.json",
        data=review_summary,
    )
    if no_changes_produced:
        return {
            "overall_status": "failed",
            "task_succeeded": False,
            "summary": f"Live Codex {mode_label} execution produced no changes",
            "key_findings": ["codex_produced_no_changes"],
        }
    if not post_run_passed:
        return {
            "overall_status": "failed",
            "task_succeeded": False,
            "summary": f"Live Codex {mode_label} post-run validation failed",
            "key_findings": [check["name"] for check in post_run_checks if not check["passed"]],
        }
    return {
        "overall_status": "ok",
        "task_succeeded": True,
        "stop_in_review": True,
        "summary": f"Live Codex {mode_label} task is ready for Rusty review",
        "key_findings": [f"Codex {mode_label} diff requires Rusty approval before any follow-on action"],
    }


def _classify_check(label: str, result) -> tuple[str, str]:
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    combined = f"{stdout}\n{stderr}".lower()

    if result.timed_out:
        return "failed", f"{label}: command timed out"
    if result.exit_code == 127:
        return "failed", f"{label}: command unavailable"

    if result.command.startswith("systemctl is-active"):
        state = stdout.splitlines()[0].strip().lower() if stdout else "unknown"
        if result.exit_code == 0 and state == "active":
            return "ok", f"{label}: service is active"
        if state in {"activating", "reloading", "deactivating"}:
            return "warning", f"{label}: service is {state}"
        return "failed", f"{label}: service is {state}"

    if result.command.startswith("systemctl status"):
        if result.exit_code != 0:
            return "failed", f"{label}: service status check failed"
        if "degraded" in combined or "reloading" in combined:
            return "warning", f"{label}: service status includes warnings"
        return "ok", f"{label}: service status is readable"

    if result.command.startswith("docker ps"):
        if result.exit_code != 0:
            return "failed", f"{label}: Docker inspection failed"
        rows = [line for line in stdout.splitlines() if line.strip()]
        if len(rows) <= 1:
            return "warning", f"{label}: Docker inspection completed, but no containers were listed"
        unhealthy_markers = ("unhealthy", "restarting", "dead", "exited")
        if any(marker in combined for marker in unhealthy_markers):
            return "failed", f"{label}: Docker reports unhealthy container state"
        return "ok", f"{label}: Docker containers are listed without unhealthy state"

    if result.exit_code == 0:
        return "ok", f"{label}: command completed"
    return "failed", f"{label}: command failed with exit code {result.exit_code}"


def _health_summary(overall_status: str, key_findings: list[str]) -> str:
    if overall_status == "ok":
        return "Health check completed: all findings are healthy"
    if overall_status == "warning":
        return "Health check completed: warnings found, no hard failures"
    return "Health check failed: inspection could not complete correctly or a required check failed"


def run_health_check(task_id: str, run_id: str) -> dict[str, Any]:
    checks = []
    for label, results in (
        ("caddy", inspect_caddy()),
        ("kairoke.service", inspect_service("kairoke.service")),
        ("docker", inspect_docker_health()),
    ):
        for result in results:
            record_worker_execution(run_id, "shell_ops", result)
            status, finding = _classify_check(label, result)
            if status not in HEALTH_STATUSES:
                raise ValueError(f"Unknown health status: {status}")
            checks.append(
                {
                    "label": label,
                    "status": status,
                    "finding": finding,
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
    key_findings = [check["finding"] for check in checks if check["status"] in {"warning", "failed"}]
    if not key_findings:
        key_findings = [check["finding"] for check in checks]

    if any(check["status"] == "failed" for check in checks):
        overall_status = "failed"
    elif any(check["status"] == "warning" for check in checks):
        overall_status = "warning"
    else:
        overall_status = "ok"

    task_succeeded = overall_status in {"ok", "warning"}
    summary = _health_summary(overall_status, key_findings)
    artifact_path = write_json_artifact(
        task_id=task_id,
        run_id=run_id,
        artifact_type="health_check",
        label=HEALTH_CHECK_TITLE,
        data={
            "overall_status": overall_status,
            "summary": summary,
            "key_findings": key_findings,
            "task_succeeded": task_succeeded,
            "checks": checks,
        },
    )
    record_event("artifact_created", f"Wrote health-check artifact: {artifact_path}", task_id=task_id, run_id=run_id)
    return {
        "overall_status": overall_status,
        "task_succeeded": task_succeeded,
        "summary": summary,
        "key_findings": key_findings,
    }
