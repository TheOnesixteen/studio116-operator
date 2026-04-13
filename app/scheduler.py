from __future__ import annotations

from app.locks import attach_run_to_lock, heartbeat_lock, scheduler_lock
from app.task_engine import create_run, finish_run, get_task, next_queued_task, run_health_check, transition_task


def run_next(task_id: str | None = None) -> dict:
    task = get_task(task_id) if task_id else next_queued_task()
    if not task:
        return {"ran": False, "message": "No queued task found"}
    if task["status"] != "queued":
        return {"ran": False, "message": f"Task is {task['status']}, not queued", "task_id": task["id"]}

    run_id: str | None = None
    with scheduler_lock(task_id=task["id"]) as lock_id:
        run_id = create_run(task["id"], worker_name="shell_ops", run_type=task["type"] or "task")
        try:
            attach_run_to_lock(lock_id, run_id)
            heartbeat_lock(lock_id)
            transition_task(task["id"], "planning", message="Scheduler planning Phase 1 read-only task")
            transition_task(task["id"], "ready", message="Task ready for read-only execution")
            transition_task(task["id"], "running", message="Task running under scheduler-owned lock")

            if task["type"] == "health_check":
                health_result = run_health_check(task["id"], run_id)
            else:
                health_result = {
                    "overall_status": "failed",
                    "task_succeeded": False,
                    "summary": f"Unsupported Phase 1 task type: {task['type']}",
                    "key_findings": [f"Unsupported Phase 1 task type: {task['type']}"],
                }

            transition_task(task["id"], "review", message="Task moved to review after execution")
            if health_result["task_succeeded"]:
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
                "ran": True,
                "ok": health_result["task_succeeded"],
                "task_id": task["id"],
                "run_id": run_id,
            }
        except Exception as exc:
            if run_id:
                finish_run(run_id, task_id=task["id"], status="failed", exit_code=1, summary=str(exc))
            current = get_task(task["id"])
            if current and current["status"] not in {"done", "failed", "canceled"}:
                transition_task(task["id"], "failed", message=str(exc))
            raise
