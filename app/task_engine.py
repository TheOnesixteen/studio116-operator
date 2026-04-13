from __future__ import annotations

import json
import uuid
from typing import Any

from adapters.base import worker_packet
from adapters.claude_code import intended_read_only_command
from adapters.codex import intended_dry_run_command
from app.artifact_store import write_json_artifact
from app.config import get_settings
from app.db import transaction
from app.events import record_event, utc_now
from app.models import HEALTH_STATUSES
from app.state_manager import assert_transition, validate_status
from tools.git_tools import create_worktree, delegated_branch_name, delegated_worktree_path
from tools.caddy_tools import inspect_caddy
from tools.docker_tools import inspect_docker_health
from tools.systemd_tools import inspect_service


HEALTH_CHECK_TITLE = "Inspect Caddy, kairoke.service, and Docker health"
HEALTH_CHECK_GOAL = "Read-only inspection of Caddy, kairoke.service, and Docker health"


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
    if worker not in {"codex", "claude_code"}:
        raise PermissionError(f"First Phase 2 slice does not support worker: {worker}")

    settings = get_settings()
    read_only = worker == "claude_code" or bool(routing.get("read_only"))
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
    else:
        intended_command = intended_read_only_command(packet_path=packet_path)
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
