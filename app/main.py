from __future__ import annotations

import argparse
import json
import sys

from app.config import get_settings
from app.db import init_db
from app.locks import active_locks
from app.models import TASK_STATES
from app.router import create_delegated_dry_run_task, create_health_check_task, create_live_codex_docs_only_task
from app.scheduler import run_next
from app.task_engine import approve_task, create_task, list_tasks, reject_task, show_task
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
    create.add_argument("--delegation-mode", choices=("dry_run", "live_codex_docs_only"), default="dry_run")
    create.add_argument("--read-only", action="store_true")

    show = task_subparsers.add_parser("show")
    show.add_argument("task_id")
    approve = task_subparsers.add_parser("approve")
    approve.add_argument("task_id")
    reject = task_subparsers.add_parser("reject")
    reject.add_argument("task_id")

    tasks = subparsers.add_parser("tasks")
    tasks_subparsers = tasks.add_subparsers(dest="tasks_command", required=True)
    tasks_subparsers.add_parser("list")

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
