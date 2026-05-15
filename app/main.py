from __future__ import annotations

import argparse
import json
import sys

from app.config import get_settings
from app.db import init_db, transaction
from app.locks import active_locks
from app.models import TASK_STATES
from app.policies import validate_policy_registry
from app.project_registry import (
    dry_run_external_worktree,
    get_project,
    load_projects,
    ordered_projects,
    preflight_project_write,
    project_context_for_task,
    validate_registry,
)
from app.router import (
    create_delegated_dry_run_task,
    create_health_check_task,
    create_live_codex_docs_only_task,
    create_live_codex_model_file_task,
    create_live_codex_policy_file_task,
    create_live_codex_scaffold_only_task,
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
    create.add_argument("--worker", choices=("codex", "claude_code", "gemini_cli"))
    create.add_argument(
        "--delegation-mode",
        choices=(
            "dry_run",
            "live_codex_docs_only",
            "live_codex_tests_only",
            "live_codex_policy_file_only",
            "live_codex_model_file_only",
            "live_codex_scaffold_only",
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

    projects = subparsers.add_parser("projects")
    projects_subparsers = projects.add_subparsers(dest="projects_command", required=True)
    projects_subparsers.add_parser("list")
    project_show = projects_subparsers.add_parser("show")
    project_show.add_argument("slug")
    projects_subparsers.add_parser("validate")
    preflight_write = projects_subparsers.add_parser("preflight-write")
    preflight_write.add_argument("slug")
    preflight_write.add_argument("--lane", required=True)
    preflight_write.add_argument("--worker", required=True)
    dry_run_worktree = projects_subparsers.add_parser("dry-run-worktree")
    dry_run_worktree.add_argument("slug")
    dry_run_worktree.add_argument("--lane", required=True)
    dry_run_worktree.add_argument("--worker", required=True)

    policies = subparsers.add_parser("policies")
    policies_subparsers = policies.add_subparsers(dest="policies_command", required=True)
    policies_subparsers.add_parser("validate")

    return parser


def print_task_summary(task: dict) -> None:
    print(f"{task['id']}  {task['status']}  {task['project']}  {task['title']}")


def print_task_show(task_view: dict) -> None:
    metadata = _task_metadata(task_view["task"])
    project_context = metadata.get("project_context")
    if not isinstance(project_context, dict):
        print(json.dumps(task_view, indent=2, sort_keys=True))
        return

    task = task_view["task"]
    print("Task")
    print(f"  id: {task['id']}")
    print(f"  title: {task['title']}")
    print(f"  status: {task['status']}")
    print(f"  project: {task['project']}")
    print()
    print("Project context")
    print(f"  slug: {project_context.get('slug') or 'unavailable'}")
    print(f"  name: {project_context.get('name') or 'unavailable'}")
    print(f"  repo_path: {project_context.get('repo_path') or 'unavailable'}")
    print(f"  stack: {_format_project_list(project_context.get('stack') or [])}")
    print(f"  domains: {_format_project_list(project_context.get('domains') or [])}")
    print(f"  services: {_format_project_list(project_context.get('services') or [])}")
    print(f"  allowed_agents: {_format_project_list(project_context.get('allowed_agents') or [])}")
    print(f"  deployment_method: {project_context.get('deployment_method') or 'unavailable'}")
    print(f"  status: {project_context.get('status') or 'unavailable'}")
    print(f"  notes: {project_context.get('notes') or 'unavailable'}")
    print(f"  source: {metadata.get('project_context_source') or 'unavailable'}")
    print()
    print("Raw task JSON")
    print(json.dumps(task_view, indent=2, sort_keys=True))


def _task_metadata(task: dict) -> dict:
    try:
        metadata = json.loads(task.get("metadata_json") or "{}")
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


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


def print_projects_list(projects: list[dict]) -> None:
    print("Projects")
    for project in projects:
        domains = ", ".join(project["domains"]) if project["domains"] else "none"
        agents = ", ".join(project["allowed_agents"])
        print(f"- {project['slug']}  {project['name']}")
        print(f"  status: {project['status']}")
        print(f"  deployment: {project['deployment_method']}")
        print(f"  agents: {agents}")
        print(f"  domains: {domains}")


def print_project_detail(project: dict) -> None:
    print(f"{project['name']} ({project['slug']})")
    print(f"status: {project['status']}")
    print(f"repo_path: {project['repo_path']}")
    print(f"stack: {_format_project_list(project['stack'])}")
    print(f"domains: {_format_project_list(project['domains'])}")
    print(f"services: {_format_project_list(project['services'])}")
    print(f"allowed_agents: {_format_project_list(project['allowed_agents'])}")
    print(f"deployment_method: {project['deployment_method']}")
    print(f"notes: {project['notes']}")
    print("write_policy:")
    write_policy = project.get("write_policy")
    if not isinstance(write_policy, dict):
        print("  writable: false")
        print("  source: absent; treated as non-writable")
        return
    print(f"  writable: {_format_bool(write_policy.get('writable'))}")
    print(f"  allowed_write_agents: {_format_project_list(write_policy.get('allowed_write_agents') or [])}")
    print(f"  allowed_lane: {_format_nullable(write_policy.get('allowed_lane'))}")
    print(f"  max_changed_files: {_format_nullable(write_policy.get('max_changed_files'))}")
    print(f"  allow_file_creation: {_format_bool(write_policy.get('allow_file_creation'))}")
    print(f"  requires_human_approval: {_format_bool(write_policy.get('requires_human_approval'))}")
    print(f"  deployment_allowed: {_format_bool(write_policy.get('deployment_allowed'))}")


def print_external_write_preflight(result: dict) -> None:
    project = result.get("project")
    write_policy = result["write_policy"]
    status = "authorized" if result["authorized"] else "blocked"
    print(f"External write preflight: {status}")
    print()
    if isinstance(project, dict):
        print(f"Project: {project['name']} ({project['slug']})")
        print(f"Status: {project['status']}")
        print(f"Repo: {project['repo_path']}")
    else:
        print(f"Project: {result['requested_project']}")
    print(f"Requested worker: {result['requested_worker']}")
    print(f"Requested lane: {result['requested_lane']}")
    print()
    print(f"Result: {result['result_code']}")
    print()
    if result["authorized"]:
        print("Why authorized:")
    else:
        print("Why blocked:")
    for reason in result["reasons"]:
        print(f"- {reason}")
    print()
    print("Policy:")
    if isinstance(project, dict):
        print(f"- allowed_agents: {_format_project_list(project.get('allowed_agents') or [])}")
    else:
        print("- allowed_agents: unavailable")
    print(f"- allowed_write_agents: {_format_project_list(write_policy.get('allowed_write_agents') or [])}")
    print(f"- allowed_lane: {_format_nullable(write_policy.get('allowed_lane'))}")
    print(f"- max_changed_files: {_format_nullable(write_policy.get('max_changed_files'))}")
    print(f"- allow_file_creation: {_format_bool(write_policy.get('allow_file_creation'))}")
    print(f"- requires_human_approval: {_format_bool(write_policy.get('requires_human_approval'))}")
    print(f"- deployment_allowed: {_format_bool(write_policy.get('deployment_allowed'))}")
    print()
    print("Next:")
    for action in result["next_actions"]:
        print(f"- {action}")
    if not result["authorized"]:
        print("- This command did not create a worktree, launch Codex, promote patches, or deploy.")


def print_external_worktree_dry_run(result: dict) -> None:
    project = result.get("project")
    preflight = result["preflight"]
    repo_checks = result["repo_checks"]
    worktree_plan = result["worktree_plan"]
    status = "would be safe" if result["safe"] else "blocked"
    print(f"External worktree dry-run: {status}")
    print()
    if isinstance(project, dict):
        print(f"Project: {project['name']} ({project['slug']})")
        print(f"Status: {project['status']}")
        print(f"Repo: {project['repo_path']}")
    else:
        print(f"Project: {preflight.requested_project}")
    print(f"Requested worker: {preflight.requested_worker}")
    print(f"Requested lane: {preflight.requested_lane}")
    print()
    print("Policy preflight:")
    print(f"- result: {preflight.result_code}")
    print(f"- authorized: {_format_bool(preflight.authorized)}")
    if isinstance(project, dict):
        write_policy = preflight.write_policy
        print(f"- allowed_agents: {_format_project_list(project.get('allowed_agents') or [])}")
        print(f"- allowed_write_agents: {_format_project_list(write_policy.get('allowed_write_agents') or [])}")
        print(f"- allowed_lane: {_format_nullable(write_policy.get('allowed_lane'))}")
        print(f"- max_changed_files: {_format_nullable(write_policy.get('max_changed_files'))}")
        print(f"- deployment_allowed: {_format_bool(write_policy.get('deployment_allowed'))}")
    print()
    print(f"Result: {result['result_code']}")
    print()
    if result["safe"]:
        print("Why safe:")
    else:
        print("Why blocked:")
    for reason in result["reasons"]:
        print(f"- {reason}")
    if repo_checks:
        print()
        print("Canonical repo checks:")
        print(f"- repo_path exists: {_format_bool(repo_checks.get('exists'))}")
        print(f"- repo_path is directory: {_format_bool(repo_checks.get('is_directory'))}")
        print(f"- git work tree: {repo_checks.get('is_git_work_tree') or 'unavailable'}")
        print(f"- git top level: {repo_checks.get('git_top_level') or 'unavailable'}")
        print(f"- HEAD: {repo_checks.get('head') or 'unavailable'}")
        clean = repo_checks.get("status_porcelain") == ""
        print(f"- canonical repo clean: {_format_bool(clean)}")
    if worktree_plan:
        print()
        print("Intended worktree plan:")
        print(f"- worktree path: {worktree_plan.get('worktree_path')}")
        print(f"- worktree path under runtime/worktrees: {_format_bool(worktree_plan.get('worktree_path_under_runtime_worktrees'))}")
        print(f"- worktree path already exists: {_format_bool(worktree_plan.get('worktree_path_exists'))}")
        print(f"- branch name: {worktree_plan.get('branch_name')}")
        print(f"- command not run: {worktree_plan.get('intended_command')}")
    print()
    print("Next:")
    for action in result["next_actions"]:
        print(f"- {action}")
    if result["safe"]:
        print("- no worktree was created")
        print("- no worker was launched")
        print("- no patch was promoted")
        print("- no deployment occurred")
    else:
        print("- This command did not create a worktree, launch Codex, promote patches, or deploy.")


def _format_project_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _format_bool(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return "unavailable"


def _format_nullable(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, list):
        return _format_project_list([str(item) for item in value])
    return str(value)


def attach_task_metadata(task_id: str, metadata: dict) -> None:
    if not metadata:
        return
    with transaction() as conn:
        row = conn.execute("SELECT metadata_json FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return
        existing = json.loads(row["metadata_json"] or "{}")
        existing.update(metadata)
        conn.execute("UPDATE tasks SET metadata_json = ? WHERE id = ?", (json.dumps(existing, sort_keys=True), task_id))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "projects" and args.projects_command == "list":
            validation = validate_registry()
            if not validation.ok:
                raise ValueError("project registry is invalid; run scripts/operator projects validate")
            print_projects_list(ordered_projects(load_projects()))
            return 0

        if args.command == "projects" and args.projects_command == "show":
            validation = validate_registry()
            if not validation.ok:
                raise ValueError("project registry is invalid; run scripts/operator projects validate")
            print_project_detail(get_project(args.slug))
            return 0

        if args.command == "projects" and args.projects_command == "validate":
            validation = validate_registry()
            if validation.ok:
                print("Project registry is valid.")
                return 0
            print("Project registry is invalid.")
            for error in validation.errors:
                print(f"- {error}")
            return 1

        if args.command == "projects" and args.projects_command == "preflight-write":
            validation = validate_registry()
            if not validation.ok:
                raise ValueError("project registry is invalid; run scripts/operator projects validate")
            result = preflight_project_write(args.slug, worker=args.worker, lane=args.lane)
            print_external_write_preflight(result.__dict__)
            return 0 if result.authorized else 1

        if args.command == "projects" and args.projects_command == "dry-run-worktree":
            validation = validate_registry()
            if not validation.ok:
                raise ValueError("project registry is invalid; run scripts/operator projects validate")
            result = dry_run_external_worktree(args.slug, worker=args.worker, lane=args.lane)
            print_external_worktree_dry_run(result.__dict__)
            return 0 if result.safe else 1

        if args.command == "policies" and args.policies_command == "validate":
            validation = validate_policy_registry()
            if validation.ok:
                print("Policy registry is valid.")
                return 0
            print("Policy registry is invalid.")
            for error in validation.errors:
                print(f"- {error}")
            return 1

        if args.command == "task" and args.task_command == "create":
            project_metadata = project_context_for_task(args.project)
            init_db()
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
                elif args.delegation_mode == "live_codex_scaffold_only":
                    if args.worker != "codex":
                        raise ValueError("live_codex_scaffold_only requires --worker codex")
                    task_id = create_live_codex_scaffold_only_task(
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
                    metadata=project_metadata,
                )
            attach_task_metadata(task_id, project_metadata)
            print(task_id)
            return 0

        init_db()

        if args.command == "task" and args.task_command == "show":
            print_task_show(show_task(args.task_id))
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
