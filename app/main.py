from __future__ import annotations

import argparse
import json
import sys

from app.config import get_settings
from app.db import init_db
from app.locks import active_locks
from app.models import TASK_STATES
from app.router import (
    create_delegated_dry_run_task,
    create_health_check_task,
    create_live_codex_docs_only_task,
    create_live_codex_model_file_task,
    create_live_codex_policy_file_task,
    create_live_codex_tests_only_task,
)
from app.scheduler import run_next
from app.task_engine import approve_task, create_task, list_tasks, reject_task, show_task, task_inbox
from tools.log_tools import tail_operator_log


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="operator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    task = subparsers.add_parser("task")
    task_subparsers = task.add_subparsers(dest="task_command", required=True)

    create = task_subparsers.add_parser("create")
    create.add_argument("--project", required=True)
    create.add_argument("--type", dest="task_type", default="health_check")
    create.add_argument("--title", required=True)
    create.add_argument("--goal", required=True)
    create.add_argument("--priority", default="medium")
    create.add_argument("--requested-by", default="Rusty")
    create.add_argument("--worker", choices=("codex", "claude_code"))
    create.add_argument(
        "--delegation-mode",
        choices=(
            "dry_run",
            "live_codex_docs_only",
            "live_codex_tests_only",
            "live_codex_policy_file_only",
            "live_codex_model_file_only",
        ),
        default="dry_run",
    )
    create.add_argument("--read-only", action="store_true")
    create.add_argument("--target-path", action="append", dest="target_paths")

    show = task_subparsers.add_parser("show")
    show.add_argument("task_id")
    approve = task_subparsers.add_parser("approve")
    approve.add_argument("task_id")
    reject = task_subparsers.add_parser("reject")
    reject.add_argument("task_id")

    tasks = subparsers.add_parser("tasks")
    tasks_subparsers = tasks.add_subparsers(dest="tasks_command", required=True)
    tasks_subparsers.add_parser("list")
    tasks_subparsers.add_parser("inbox")

    run = subparsers.add_parser("run")
    run_subparsers = run.add_subparsers(dest="run_command", required=True)
    run_subparsers.add_parser("next")

    subparsers.add_parser("status")

    logs = subparsers.add_parser("logs")
    logs_subparsers = logs.add_subparsers(dest="logs_command", required=True)
    tail = logs_subparsers.add_parser("tail", description="Tail Operator/runtime logs only in Phase 1.")
    tail.add_argument("--lines", type=int, default=50)

    health = subparsers.add_parser("health")
    health_subparsers = health.add_subparsers(dest="health_command", required=True)
    health_subparsers.add_parser("check")

    return parser


def print_task_summary(task: dict) -> None:
    print(f"{task['id']}  {task['status']}  {task['project']}  {task['title']}")


def print_task_inbox(inbox: dict) -> None:
    if inbox["task_count"] == 0:
        print("No tasks found. Operator is idle.")
        return

    print("Task Inbox")
    print("Counts by status")
    counts = inbox["counts"]
    visible_counts = [f"{status}: {count}" for status, count in counts.items() if count]
    print(", ".join(visible_counts) if visible_counts else "none")
    print(f"Tasks untouched for {inbox['stale_after_days']}+ days appear under Older unresolved work.")
    print()

    print("Needs attention now")
    if not inbox["current_unresolved"]:
        print("Nothing needs attention right now.")
    for task in inbox["current_unresolved"]:
        _print_inbox_task(task, stale=False)
    print()

    print("Older unresolved work")
    if not inbox["stale_unresolved"]:
        print("- none")
    for task in inbox["stale_unresolved"]:
        _print_inbox_task(task, stale=True)
    print()

    print("Active locks")
    locks = inbox["active_locks"]
    if not locks:
        print("- none")
    for lock in locks:
        task_id = lock.get("task_id") or "none"
        print(f"- {lock['lock_type']}:{lock['resource_key']} task={task_id} acquired={lock['acquired_at']}")


def _print_inbox_task(task: dict, *, stale: bool) -> None:
    status_label = task["status"].upper()
    prefix = f"STALE {status_label}" if stale else status_label
    print(f"- {prefix} {task['id']}  {task['title']}")
    print(f"  age: {task['age_days']}d")
    print(f"  updated: {task.get('updated_at') or 'unavailable'}")
    latest_run = task.get("latest_run") or {}
    if task["status"] == "review":
        print(f"  changed files: {_format_changed_files(task['changed_files'])}")
        print(f"  next: scripts/operator task show {task['id']}")
        print(f"        scripts/operator task approve {task['id']}")
        print(f"        scripts/operator task reject {task['id']}")
    elif task["status"] == "failed":
        print(f"  latest run: {latest_run.get('summary') or 'unavailable'}")
        print(f"  next: scripts/operator task show {task['id']}")
    elif task["status"] == "running":
        print(f"  started: {task.get('started_at') or latest_run.get('started_at') or 'unavailable'}")
        print(f"  heartbeat: {latest_run.get('heartbeat_at') or 'unavailable'}")
        print(f"  next: scripts/operator task show {task['id']}")
    else:
        print(f"  next: scripts/operator task show {task['id']}")


def _format_changed_files(changed_files: list[str] | None) -> str:
    if changed_files is None:
        return "unavailable"
    if not changed_files:
        return "none"
    return ", ".join(changed_files)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    init_db()

    try:
        if args.command == "task" and args.task_command == "create":
            if args.task_type == "delegated":
                if not args.worker:
                    raise ValueError("--worker is required for delegated tasks")
                if args.delegation_mode == "live_codex_docs_only":
                    if args.worker != "codex":
                        raise ValueError("live_codex_docs_only requires --worker codex")
                    task_id = create_live_codex_docs_only_task(
                        project=args.project,
                        title=args.title,
                        goal=args.goal,
                        target_paths=args.target_paths,
                        requested_by=args.requested_by,
                    )
                elif args.delegation_mode == "live_codex_tests_only":
                    if args.worker != "codex":
                        raise ValueError("live_codex_tests_only requires --worker codex")
                    task_id = create_live_codex_tests_only_task(
                        project=args.project,
                        title=args.title,
                        goal=args.goal,
                        target_paths=args.target_paths,
                        requested_by=args.requested_by,
                    )
                elif args.delegation_mode == "live_codex_policy_file_only":
                    if args.worker != "codex":
                        raise ValueError("live_codex_policy_file_only requires --worker codex")
                    task_id = create_live_codex_policy_file_task(
                        project=args.project,
                        title=args.title,
                        goal=args.goal,
                        target_paths=args.target_paths,
                        requested_by=args.requested_by,
                    )
                elif args.delegation_mode == "live_codex_model_file_only":
                    if args.worker != "codex":
                        raise ValueError("live_codex_model_file_only requires --worker codex")
                    task_id = create_live_codex_model_file_task(
                        project=args.project,
                        title=args.title,
                        goal=args.goal,
                        target_paths=args.target_paths,
                        requested_by=args.requested_by,
                    )
                else:
                    task_id = create_delegated_dry_run_task(
                        project=args.project,
                        title=args.title,
                        goal=args.goal,
                        worker=args.worker,
                        read_only=args.read_only,
                        requested_by=args.requested_by,
                    )
            else:
                task_id = create_task(
                    project=args.project,
                    task_type=args.task_type,
                    title=args.title,
                    goal=args.goal,
                    priority=args.priority,
                    requested_by=args.requested_by,
                )
            print(task_id)
            return 0

        if args.command == "task" and args.task_command == "show":
            print(json.dumps(show_task(args.task_id), indent=2, sort_keys=True))
            return 0

        if args.command == "task" and args.task_command == "approve":
            print(json.dumps(approve_task(args.task_id), indent=2, sort_keys=True))
            return 0

        if args.command == "task" and args.task_command == "reject":
            print(json.dumps(reject_task(args.task_id), indent=2, sort_keys=True))
            return 0

        if args.command == "tasks" and args.tasks_command == "list":
            for task in list_tasks():
                print_task_summary(task)
            return 0

        if args.command == "tasks" and args.tasks_command == "inbox":
            print_task_inbox(task_inbox())
            return 0

        if args.command == "run" and args.run_command == "next":
            result = run_next()
            print(json.dumps(result, indent=2))
            return 0 if result.get("ok", True) else 1

        if args.command == "status":
            tasks = list_tasks()
            counts: dict[str, int] = {status: 0 for status in TASK_STATES}
            for task in tasks:
                counts[task["status"]] = counts.get(task["status"], 0) + 1
            settings = get_settings()
            locks = active_locks()
            print(
                json.dumps(
                    {
                        "db": str(settings.db_path),
                        "operator_runtime_log": str(settings.operator_log_path),
                        "task_counts": counts,
                        "active_lock_count": len(locks),
                        "active_locks": locks,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "logs" and args.logs_command == "tail":
            print(f"Operator/runtime log only (Phase 1): {get_settings().operator_log_path}")
            print(tail_operator_log(args.lines, get_settings().operator_log_path))
            return 0

        if args.command == "health" and args.health_command == "check":
            task_id = create_health_check_task()
            result = run_next(task_id)
            print(json.dumps(result, indent=2))
            return 0 if result.get("ok", False) else 1
    except Exception as exc:
        print(f"operator error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
