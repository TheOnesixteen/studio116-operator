from __future__ import annotations

import argparse
import json
import sys

from app.config import get_settings
from app.db import init_db
from app.router import create_health_check_task
from app.scheduler import run_next
from app.task_engine import create_task, list_tasks, show_task
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

    show = task_subparsers.add_parser("show")
    show.add_argument("task_id")

    tasks = subparsers.add_parser("tasks")
    tasks_subparsers = tasks.add_subparsers(dest="tasks_command", required=True)
    tasks_subparsers.add_parser("list")

    run = subparsers.add_parser("run")
    run_subparsers = run.add_subparsers(dest="run_command", required=True)
    run_subparsers.add_parser("next")

    subparsers.add_parser("status")

    logs = subparsers.add_parser("logs")
    logs_subparsers = logs.add_subparsers(dest="logs_command", required=True)
    tail = logs_subparsers.add_parser("tail")
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
            task_id = create_task(
                project=args.project,
                task_type=args.task_type,
                title=args.title,
                goal=args.goal,
                priority=args.priority,
            )
            print(task_id)
            return 0

        if args.command == "task" and args.task_command == "show":
            print(json.dumps(show_task(args.task_id), indent=2, sort_keys=True))
            return 0

        if args.command == "tasks" and args.tasks_command == "list":
            for task in list_tasks():
                print_task_summary(task)
            return 0

        if args.command == "run" and args.run_command == "next":
            result = run_next()
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result.get("ok", True) else 1

        if args.command == "status":
            tasks = list_tasks()
            counts: dict[str, int] = {}
            for task in tasks:
                counts[task["status"]] = counts.get(task["status"], 0) + 1
            print(json.dumps({"db": str(get_settings().db_path), "task_counts": counts}, indent=2, sort_keys=True))
            return 0

        if args.command == "logs" and args.logs_command == "tail":
            print(tail_operator_log(args.lines, get_settings().operator_log_path))
            return 0

        if args.command == "health" and args.health_command == "check":
            task_id = create_health_check_task()
            result = run_next(task_id)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result.get("ok", False) else 1
    except Exception as exc:
        print(f"operator error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
