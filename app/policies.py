from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

from app.config import get_settings


READ_ONLY_ACTIONS = {
    "inspect_files",
    "read_logs",
    "docker_ps",
    "docker_logs",
    "service_status_checks",
}

BLOCKED_PHASE1_ACTIONS = {
    "deploy_to_production",
    "systemctl_restart",
    "systemctl_stop",
    "docker_compose_down",
    "docker_system_prune",
    "rm_rf_anything",
    "edit_caddy_config",
    "edit_live_env_files",
    "dns_or_ssl_changes",
    "delete_database_records",
    "delete_production_data",
    "expose_api_keys_in_output",
    "expose_secrets_in_logs",
    "auto_deploy_without_approval",
    "run_unknown_scripts_from_internet",
}


def _read_yaml_list(path: Path, section: str) -> set[str]:
    if not path.exists():
        return set()
    values: set[str] = set()
    current_section: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and line.endswith(":"):
            current_section = line[:-1]
            continue
        if current_section == section and line.strip().startswith("- "):
            values.add(line.strip()[2:].strip())
    return values


def allowed_without_approval() -> set[str]:
    configured = _read_yaml_list(get_settings().policies_path, "allowed_without_approval")
    return configured or READ_ONLY_ACTIONS


def requires_approval_or_blocked() -> set[str]:
    settings = get_settings()
    return (
        _read_yaml_list(settings.policies_path, "requires_approval")
        | _read_yaml_list(settings.policies_path, "never_allowed")
        | BLOCKED_PHASE1_ACTIONS
    )


def assert_phase1_allowed(action: str) -> None:
    if action in requires_approval_or_blocked():
        raise PermissionError(f"Phase 1 blocks action: {action}")
    if action not in allowed_without_approval():
        raise PermissionError(f"Phase 1 does not allow action without approval: {action}")


LIVE_CODEX_DOCS_ONLY_MODE = "live_codex_docs_only"
LIVE_CODEX_DOCS_ONLY_TARGETS = ["README.md"]
LIVE_CODEX_TIMEOUT_SECONDS = 600
LIVE_CODEX_MAX_CHANGED_FILES = 5
LIVE_CODEX_DOCS_ONLY_ALLOWED_TARGETS_SECTION = "live_codex_docs_only_allowed_targets"


def is_forbidden_live_codex_path(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1] if parts else path
    if path.startswith(".") or "/." in path:
        return True
    if name.endswith(".env") or name == ".env" or ".env." in name:
        return True
    lowered = path.lower()
    forbidden_tokens = (
        "deploy",
        "caddy",
        "systemd",
        ".service",
        "docker-compose",
        "compose.yaml",
        "compose.yml",
        "config",
        "secret",
        "key",
    )
    return any(token in lowered for token in forbidden_tokens)


def live_codex_docs_only_allowed_targets() -> list[str]:
    configured = _read_yaml_list(get_settings().policies_path, LIVE_CODEX_DOCS_ONLY_ALLOWED_TARGETS_SECTION)
    return sorted(configured) if configured else list(LIVE_CODEX_DOCS_ONLY_TARGETS)


def _path_is_repo_relative(path: str) -> bool:
    candidate = Path(path)
    return not candidate.is_absolute() and ".." not in candidate.parts and path not in {"", "."}


def _path_matches_allowed_target(path: str, allowed_targets: list[str]) -> bool:
    return any(fnmatchcase(path, allowed) for allowed in allowed_targets)


def validate_live_codex_docs_only_paths(paths: list[str]) -> list[dict]:
    allowed_targets = live_codex_docs_only_allowed_targets()
    return [
        {
            "name": "path_count_at_least_1",
            "passed": len(paths) >= 1,
            "details": {"count": len(paths)},
        },
        {
            "name": "path_count_at_most_5",
            "passed": len(paths) <= LIVE_CODEX_MAX_CHANGED_FILES,
            "details": {"count": len(paths), "max": LIVE_CODEX_MAX_CHANGED_FILES},
        },
        {
            "name": "paths_are_repo_relative",
            "passed": all(_path_is_repo_relative(path) for path in paths),
            "details": {"paths": paths},
        },
        {
            "name": "paths_are_markdown_docs",
            "passed": all(path.endswith(".md") for path in paths),
            "details": {"paths": paths},
        },
        {
            "name": "paths_are_policy_allowed",
            "passed": all(_path_matches_allowed_target(path, allowed_targets) for path in paths),
            "details": {"paths": paths, "allowed_targets": allowed_targets},
        },
        {
            "name": "no_hidden_files",
            "passed": all(not (path.startswith(".") or "/." in path) for path in paths),
            "details": {"paths": paths},
        },
        {
            "name": "no_env_files",
            "passed": all(not (path.endswith(".env") or path == ".env" or ".env." in path) for path in paths),
            "details": {"paths": paths},
        },
        {
            "name": "no_deploy_config_system_files",
            "passed": all(not is_forbidden_live_codex_path(path) for path in paths),
            "details": {"paths": paths},
        },
    ]


def live_codex_preflight_checks(
    *,
    project: str,
    worker: str,
    mode: str,
    target_paths: list[str],
    repo_root: Path,
    worktree_path: Path,
    command_cwd: Path,
    active_delegated_writer_locks: int,
    goal: str,
    constraints: list[str],
    worktree_ready: bool,
) -> list[dict]:
    repo_root = repo_root.resolve()
    worktree_resolved = worktree_path.resolve()
    runtime_worktrees = get_settings().worktrees_dir.resolve()
    goal_blob = goal.lower()
    target_path_checks = validate_live_codex_docs_only_paths(target_paths)
    checks = [
        ("project_is_operator", project == "operator"),
        ("worker_is_codex", worker == "codex"),
        ("mode_is_live_codex_docs_only", mode == LIVE_CODEX_DOCS_ONLY_MODE),
        ("target_paths_are_policy_allowed", all(check["passed"] for check in target_path_checks)),
        ("repo_root_is_operator_repo", repo_root == get_settings().repo_root.resolve()),
        ("worktree_under_runtime_worktrees", runtime_worktrees in [worktree_resolved, *worktree_resolved.parents]),
        ("canonical_checkout_not_cwd", command_cwd.resolve() != repo_root),
        ("single_live_codex_writer_available", active_delegated_writer_locks == 0),
        ("no_package_install_requested", not any(token in goal_blob for token in ("npm install", "pip install", "apt install", "brew install"))),
        ("no_network_dependent_work", not any(token in goal_blob for token in ("curl ", "wget ", "http://", "https://", "network"))),
        ("no_auto_commit_merge_push", not any(token in goal_blob for token in ("git commit", "git merge", "git push"))),
        ("timeout_is_10_minutes", LIVE_CODEX_TIMEOUT_SECONDS == 600),
        ("max_changed_files_is_5", LIVE_CODEX_MAX_CHANGED_FILES == 5),
        ("worktree_exists_or_created", worktree_ready),
        ("preflight_artifact_written", True),
    ]
    return [{"name": name, "passed": bool(passed)} for name, passed in checks] + target_path_checks


def validate_live_codex_changed_files(changed_files: list[str]) -> list[dict]:
    path_checks = validate_live_codex_docs_only_paths(changed_files)
    checks = [
        {
            "name": "changed_file_count_at_most_5",
            "passed": len(changed_files) <= LIVE_CODEX_MAX_CHANGED_FILES,
            "details": {"count": len(changed_files), "max": LIVE_CODEX_MAX_CHANGED_FILES},
        },
        {
            "name": "changed_files_are_policy_allowed",
            "passed": all(check["passed"] for check in path_checks),
            "details": {"changed_files": changed_files, "allowed": live_codex_docs_only_allowed_targets()},
        },
        {
            "name": "no_hidden_files_changed",
            "passed": all(not (path.startswith(".") or "/." in path) for path in changed_files),
            "details": {"changed_files": changed_files},
        },
        {
            "name": "no_env_files_changed",
            "passed": all(not (path.endswith(".env") or path == ".env" or ".env." in path) for path in changed_files),
            "details": {"changed_files": changed_files},
        },
        {
            "name": "no_deploy_config_system_files_changed",
            "passed": all(not is_forbidden_live_codex_path(path) for path in changed_files),
            "details": {"changed_files": changed_files},
        },
        {
            "name": "changed_paths_are_repo_relative",
            "passed": all(_path_is_repo_relative(path) for path in changed_files),
            "details": {"changed_files": changed_files},
        },
    ]
    return checks + path_checks
