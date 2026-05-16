from __future__ import annotations

import json
from contextlib import ExitStack, contextmanager

from app.config import get_settings
from app.locks import attach_run_to_lock, heartbeat_lock, managed_lock, scheduler_lock
from app.task_engine import (
    create_run,
    finish_run,
    get_task,
    next_queued_task,
    run_delegated_dry_run,
    run_live_codex_docs_only,
    run_live_codex_model_file,
    run_live_codex_policy_file,
    run_live_codex_scaffold_only,
    run_live_codex_tests_only,
    run_health_check,
    transition_task,
)
from tools.git_tools import delegated_worktree_path


def run_next(task_id: str | None = None) -> dict:
    task = get_task(task_id) if task_id else next_queued_task()
    if not task:
        return {"ran": False, "message": "No queued task found"}
    if task["status"] != "queued":
        return {"ran": False, "message": f"Task is {task['status']}, not queued", "task_id": task["id"]}

    run_id: str | None = None
    routing = _task_json(task, "routing_json", {})
    worker_name = routing.get("worker", "shell_ops") if task["type"] == "delegated" else "shell_ops"
    delegation_mode = routing.get("delegation_mode", "dry_run")
    run_type = f"delegated_{delegation_mode}" if task["type"] == "delegated" else task["type"] or "task"

    with scheduler_lock(task_id=task["id"]) as lock_id:
        run_id = create_run(task["id"], worker_name=worker_name, run_type=run_type)
        try:
            attach_run_to_lock(lock_id, run_id)
            heartbeat_lock(lock_id)
            transition_task(task["id"], "planning", message="Scheduler planning task")
            transition_task(task["id"], "ready", message="Task ready for execution")
            transition_task(task["id"], "running", message="Task running under scheduler-owned lock")

            if task["type"] == "health_check":
                health_result = run_health_check(task["id"], run_id)
            elif task["type"] == "delegated":
                with _delegation_locks(task, run_id, worker_name):
                    if delegation_mode == "live_codex_docs_only":
                        health_result = run_live_codex_docs_only(task, run_id)
                    elif delegation_mode == "live_codex_tests_only":
                        health_result = run_live_codex_tests_only(task, run_id)
                    elif delegation_mode == "live_codex_policy_file_only":
                        health_result = run_live_codex_policy_file(task, run_id)
                    elif delegation_mode == "live_codex_model_file_only":
                        health_result = run_live_codex_model_file(task, run_id)
                    elif delegation_mode == "live_codex_scaffold_only":
                        health_result = run_live_codex_scaffold_only(task, run_id)
                    else:
                        health_result = run_delegated_dry_run(task, run_id)
            else:
                health_result = {
                    "overall_status": "failed",
                    "task_succeeded": False,
                    "summary": f"Unsupported Phase 1 task type: {task['type']}",
                    "key_findings": [f"Unsupported Phase 1 task type: {task['type']}"],
                }

            transition_task(task["id"], "review", message="Task moved to review after execution")
            if health_result.get("stop_in_review"):
                finish_run(run_id, task_id=task["id"], status="review", exit_code=0, summary=health_result["summary"])
            elif health_result["task_succeeded"]:
                transition_task(task["id"], "done", message=health_result["summary"])
                finish_run(run_id, task_id=task["id"], status="done", exit_code=0, summary=health_result["summary"])
            else:
                transition_task(task["id"], "failed", message=health_result["summary"])
                finish_run(run_id, task_id=task["id"], status="failed", exit_code=1, summary=health_result["summary"])
            return {
                "overall_status": health_result["overall_status"],
                "summary": health_result["summary"],
                "key_findings": health_result["key_findings"],
                "task_succeeded": health_result["task_succeeded"],
                "stop_in_review": bool(health_result.get("stop_in_review")),
                "ran": True,
                "ok": health_result["task_succeeded"],
                "task_id": task["id"],
                "run_id": run_id,
            }
        except BaseException as exc:
            if run_id:
                finish_run(run_id, task_id=task["id"], status="failed", exit_code=1, summary=str(exc))
            current = get_task(task["id"])
            if current and current["status"] not in {"done", "failed", "canceled"}:
                transition_task(task["id"], "failed", message=str(exc))
            raise


def _task_json(task: dict, key: str, default):
    raw = task.get(key)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


@contextmanager
def _delegation_locks(task: dict, run_id: str, worker_name: str):
    stack = ExitStack()
    try:
        stack.enter_context(
            managed_lock(
                lock_type="worker",
                resource_key=worker_name,
                task_id=task["id"],
                run_id=run_id,
                worker_name="scheduler",
            )
        )
        if worker_name == "codex":
            settings = get_settings()
            worktree_path = delegated_worktree_path(task_id=task["id"], worker=worker_name)
            stack.enter_context(
                managed_lock(
                    lock_type="delegated_writer",
                    resource_key="codex",
                    task_id=task["id"],
                    run_id=run_id,
                    worker_name="scheduler",
                    metadata={"first_slice": True},
                )
            )
            stack.enter_context(
                managed_lock(
                    lock_type="repo",
                    resource_key=str(settings.repo_root),
                    task_id=task["id"],
                    run_id=run_id,
                    worker_name="scheduler",
                )
            )
            stack.enter_context(
                managed_lock(
                    lock_type="worktree",
                    resource_key=str(worktree_path),
                    task_id=task["id"],
                    run_id=run_id,
                    worker_name="scheduler",
                )
            )
        yield
    finally:
        stack.close()
