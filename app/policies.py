from __future__ import annotations

import ast
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
LIVE_CODEX_TESTS_ONLY_MODE = "live_codex_tests_only"
LIVE_CODEX_POLICY_FILE_ONLY_MODE = "live_codex_policy_file_only"
LIVE_CODEX_MODEL_FILE_ONLY_MODE = "live_codex_model_file_only"
LIVE_CODEX_DOCS_ONLY_TARGETS = ["README.md"]
LIVE_CODEX_TESTS_ONLY_TARGETS = ["tests/test_*.py"]
LIVE_CODEX_POLICY_FILE_ONLY_TARGETS = ["app/policies.py"]
LIVE_CODEX_MODEL_FILE_ONLY_TARGETS = ["app/models.py"]
LIVE_CODEX_TIMEOUT_SECONDS = 600
LIVE_CODEX_MAX_CHANGED_FILES = 5
LIVE_CODEX_DOCS_ONLY_ALLOWED_TARGETS_SECTION = "live_codex_docs_only_allowed_targets"
LIVE_CODEX_TESTS_ONLY_ALLOWED_TARGETS_SECTION = "live_codex_tests_only_allowed_targets"
LIVE_CODEX_TESTS_ONLY_DISALLOWED_IMPORT_ROOTS_SECTION = "live_codex_tests_only_disallowed_import_roots"
LIVE_CODEX_TESTS_ONLY_DISALLOWED_CALLS_SECTION = "live_codex_tests_only_disallowed_calls"
LIVE_CODEX_TESTS_ONLY_DISALLOWED_STRING_TOKENS_SECTION = "live_codex_tests_only_disallowed_string_tokens"
LIVE_CODEX_TESTS_ONLY_DISALLOWED_PATH_PREFIXES_SECTION = "live_codex_tests_only_disallowed_path_prefixes"
LIVE_CODEX_TESTS_ONLY_ALLOWED_PATH_PREFIXES_SECTION = "live_codex_tests_only_allowed_path_prefixes"
LIVE_CODEX_TESTS_ONLY_DISALLOWED_HOST_LITERALS_SECTION = "live_codex_tests_only_disallowed_host_literals"
LIVE_CODEX_POLICY_FILE_ALLOWED_TARGETS_SECTION = "live_codex_policy_file_allowed_targets"
LIVE_CODEX_POLICY_FILE_DISALLOWED_IMPORT_ROOTS_SECTION = "live_codex_policy_file_disallowed_import_roots"
LIVE_CODEX_POLICY_FILE_DISALLOWED_CALLS_SECTION = "live_codex_policy_file_disallowed_calls"
LIVE_CODEX_POLICY_FILE_REQUIRED_SYMBOLS_SECTION = "live_codex_policy_file_required_symbols"
LIVE_CODEX_MODEL_FILE_ALLOWED_TARGETS_SECTION = "live_codex_model_file_allowed_targets"
LIVE_CODEX_MODEL_FILE_DISALLOWED_IMPORT_ROOTS_SECTION = "live_codex_model_file_disallowed_import_roots"
LIVE_CODEX_MODEL_FILE_DISALLOWED_CALLS_SECTION = "live_codex_model_file_disallowed_calls"
LIVE_CODEX_MODEL_FILE_REQUIRED_SYMBOLS_SECTION = "live_codex_model_file_required_symbols"
LIVE_CODEX_MODEL_FILE_REQUIRED_FROZEN_DATACLASSES_SECTION = "live_codex_model_file_required_frozen_dataclasses"

DEFAULT_TESTS_ONLY_DISALLOWED_IMPORT_ROOTS = {
    "boto3",
    "botocore",
    "docker",
    "fabric",
    "ftplib",
    "http",
    "kubernetes",
    "paramiko",
    "requests",
    "socket",
    "smtplib",
    "telnetlib",
    "urllib",
}
DEFAULT_TESTS_ONLY_DISALLOWED_CALLS = {
    "os.popen",
    "os.system",
    "pty.spawn",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.Popen",
    "subprocess.run",
}
DEFAULT_TESTS_ONLY_DISALLOWED_STRING_TOKENS = {
    "curl ",
    "deploy-combs",
    "deploy-kairoke",
    "deploy-katie",
    "deploy-kensington",
    "deploy-robin",
    "deploy-rustyo",
    "deploy-ski",
    "deploy-studio",
    "deploy-trouper",
    "docker ",
    "docker compose",
    "docker-compose",
    "ssh ",
    "systemctl",
    "wget ",
}
DEFAULT_TESTS_ONLY_DISALLOWED_PATH_PREFIXES = {"/etc/", "/home/", "/opt/", "/root/", "/srv/", "/usr/", "/var/"}
DEFAULT_TESTS_ONLY_ALLOWED_PATH_PREFIXES = {"/root/Projects/studio116-operator", "/tmp/"}
DEFAULT_TESTS_ONLY_DISALLOWED_HOST_LITERALS = {
    "159.65.187.30",
    "combsplumbing.com",
    "do.116.studio",
    "kairoke.com",
    "kdomusic.com",
    "kensingtonpool.com",
    "robinolinger.com",
    "skilagrange.com",
}
DEFAULT_POLICY_FILE_DISALLOWED_IMPORT_ROOTS = DEFAULT_TESTS_ONLY_DISALLOWED_IMPORT_ROOTS | {"shutil", "subprocess"}
DEFAULT_POLICY_FILE_DISALLOWED_CALLS = DEFAULT_TESTS_ONLY_DISALLOWED_CALLS | {
    "os.remove",
    "os.removedirs",
    "os.rmdir",
    "shutil.rmtree",
    "unlink",
    "rmdir",
}
DEFAULT_POLICY_FILE_REQUIRED_SYMBOLS = {
    "BLOCKED_PHASE1_ACTIONS",
    "LIVE_CODEX_DOCS_ONLY_MODE",
    "LIVE_CODEX_TESTS_ONLY_MODE",
    "LIVE_CODEX_POLICY_FILE_ONLY_MODE",
    "LIVE_CODEX_MAX_CHANGED_FILES",
    "READ_ONLY_ACTIONS",
    "_read_yaml_list",
    "assert_phase1_allowed",
    "is_forbidden_live_codex_path",
    "live_codex_allowed_targets_for_mode",
    "validate_live_codex_changed_files_for_mode",
    "validate_live_codex_paths_for_mode",
    "validate_live_codex_policy_file_content",
    "validate_live_codex_tests_only_content",
}
DEFAULT_MODEL_FILE_DISALLOWED_IMPORT_ROOTS = DEFAULT_POLICY_FILE_DISALLOWED_IMPORT_ROOTS
DEFAULT_MODEL_FILE_DISALLOWED_CALLS = DEFAULT_POLICY_FILE_DISALLOWED_CALLS
DEFAULT_MODEL_FILE_REQUIRED_SYMBOLS = {
    "TASK_STATES",
    "TERMINAL_TASK_STATES",
    "HEALTH_STATUSES",
    "CommandResult",
    "HealthCheckResult",
}
DEFAULT_MODEL_FILE_REQUIRED_FROZEN_DATACLASSES = {"CommandResult", "HealthCheckResult"}


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


def live_codex_tests_only_allowed_targets() -> list[str]:
    configured = _read_yaml_list(get_settings().policies_path, LIVE_CODEX_TESTS_ONLY_ALLOWED_TARGETS_SECTION)
    return sorted(configured) if configured else list(LIVE_CODEX_TESTS_ONLY_TARGETS)


def live_codex_policy_file_allowed_targets() -> list[str]:
    configured = _read_yaml_list(get_settings().policies_path, LIVE_CODEX_POLICY_FILE_ALLOWED_TARGETS_SECTION)
    return sorted(configured) if configured else list(LIVE_CODEX_POLICY_FILE_ONLY_TARGETS)


def live_codex_model_file_allowed_targets() -> list[str]:
    configured = _read_yaml_list(get_settings().policies_path, LIVE_CODEX_MODEL_FILE_ALLOWED_TARGETS_SECTION)
    return sorted(configured) if configured else list(LIVE_CODEX_MODEL_FILE_ONLY_TARGETS)


def _policy_list(section: str, default: set[str]) -> list[str]:
    configured = _read_yaml_list(get_settings().policies_path, section)
    return sorted(configured) if configured else sorted(default)


def live_codex_tests_only_disallowed_import_roots() -> list[str]:
    return _policy_list(
        LIVE_CODEX_TESTS_ONLY_DISALLOWED_IMPORT_ROOTS_SECTION,
        DEFAULT_TESTS_ONLY_DISALLOWED_IMPORT_ROOTS,
    )


def live_codex_tests_only_disallowed_calls() -> list[str]:
    return _policy_list(LIVE_CODEX_TESTS_ONLY_DISALLOWED_CALLS_SECTION, DEFAULT_TESTS_ONLY_DISALLOWED_CALLS)


def live_codex_tests_only_disallowed_string_tokens() -> list[str]:
    return _policy_list(
        LIVE_CODEX_TESTS_ONLY_DISALLOWED_STRING_TOKENS_SECTION,
        DEFAULT_TESTS_ONLY_DISALLOWED_STRING_TOKENS,
    )


def live_codex_tests_only_disallowed_path_prefixes() -> list[str]:
    return _policy_list(
        LIVE_CODEX_TESTS_ONLY_DISALLOWED_PATH_PREFIXES_SECTION,
        DEFAULT_TESTS_ONLY_DISALLOWED_PATH_PREFIXES,
    )


def live_codex_tests_only_allowed_path_prefixes() -> list[str]:
    return _policy_list(
        LIVE_CODEX_TESTS_ONLY_ALLOWED_PATH_PREFIXES_SECTION,
        DEFAULT_TESTS_ONLY_ALLOWED_PATH_PREFIXES,
    )


def live_codex_tests_only_disallowed_host_literals() -> list[str]:
    return _policy_list(
        LIVE_CODEX_TESTS_ONLY_DISALLOWED_HOST_LITERALS_SECTION,
        DEFAULT_TESTS_ONLY_DISALLOWED_HOST_LITERALS,
    )


def live_codex_policy_file_disallowed_import_roots() -> list[str]:
    return _policy_list(
        LIVE_CODEX_POLICY_FILE_DISALLOWED_IMPORT_ROOTS_SECTION,
        DEFAULT_POLICY_FILE_DISALLOWED_IMPORT_ROOTS,
    )


def live_codex_policy_file_disallowed_calls() -> list[str]:
    return _policy_list(LIVE_CODEX_POLICY_FILE_DISALLOWED_CALLS_SECTION, DEFAULT_POLICY_FILE_DISALLOWED_CALLS)


def live_codex_policy_file_required_symbols() -> list[str]:
    return _policy_list(LIVE_CODEX_POLICY_FILE_REQUIRED_SYMBOLS_SECTION, DEFAULT_POLICY_FILE_REQUIRED_SYMBOLS)


def live_codex_model_file_disallowed_import_roots() -> list[str]:
    return _policy_list(
        LIVE_CODEX_MODEL_FILE_DISALLOWED_IMPORT_ROOTS_SECTION,
        DEFAULT_MODEL_FILE_DISALLOWED_IMPORT_ROOTS,
    )


def live_codex_model_file_disallowed_calls() -> list[str]:
    return _policy_list(LIVE_CODEX_MODEL_FILE_DISALLOWED_CALLS_SECTION, DEFAULT_MODEL_FILE_DISALLOWED_CALLS)


def live_codex_model_file_required_symbols() -> list[str]:
    return _policy_list(LIVE_CODEX_MODEL_FILE_REQUIRED_SYMBOLS_SECTION, DEFAULT_MODEL_FILE_REQUIRED_SYMBOLS)


def live_codex_model_file_required_frozen_dataclasses() -> list[str]:
    return _policy_list(
        LIVE_CODEX_MODEL_FILE_REQUIRED_FROZEN_DATACLASSES_SECTION,
        DEFAULT_MODEL_FILE_REQUIRED_FROZEN_DATACLASSES,
    )


def live_codex_allowed_targets_for_mode(mode: str) -> list[str]:
    if mode == LIVE_CODEX_MODEL_FILE_ONLY_MODE:
        return live_codex_model_file_allowed_targets()
    if mode == LIVE_CODEX_POLICY_FILE_ONLY_MODE:
        return live_codex_policy_file_allowed_targets()
    if mode == LIVE_CODEX_TESTS_ONLY_MODE:
        return live_codex_tests_only_allowed_targets()
    return live_codex_docs_only_allowed_targets()


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


def validate_live_codex_tests_only_paths(paths: list[str]) -> list[dict]:
    allowed_targets = live_codex_tests_only_allowed_targets()
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
            "name": "paths_are_tests",
            "passed": all(fnmatchcase(path, "tests/test_*.py") for path in paths),
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


def validate_live_codex_policy_file_paths(paths: list[str]) -> list[dict]:
    allowed_targets = live_codex_policy_file_allowed_targets()
    return [
        {
            "name": "path_count_exactly_1",
            "passed": len(paths) == 1,
            "details": {"count": len(paths), "required": 1},
        },
        {
            "name": "paths_are_repo_relative",
            "passed": all(_path_is_repo_relative(path) for path in paths),
            "details": {"paths": paths},
        },
        {
            "name": "paths_are_policy_file_target",
            "passed": paths == ["app/policies.py"],
            "details": {"paths": paths},
        },
        {
            "name": "paths_are_policy_file",
            "passed": paths == ["app/policies.py"],
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


def validate_live_codex_model_file_paths(paths: list[str]) -> list[dict]:
    allowed_targets = live_codex_model_file_allowed_targets()
    return [
        {
            "name": "path_count_exactly_1",
            "passed": len(paths) == 1,
            "details": {"count": len(paths), "required": 1},
        },
        {
            "name": "paths_are_repo_relative",
            "passed": all(_path_is_repo_relative(path) for path in paths),
            "details": {"paths": paths},
        },
        {
            "name": "paths_are_model_file_target",
            "passed": paths == ["app/models.py"],
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


def validate_live_codex_paths_for_mode(mode: str, paths: list[str]) -> list[dict]:
    if mode == LIVE_CODEX_MODEL_FILE_ONLY_MODE:
        return validate_live_codex_model_file_paths(paths)
    if mode == LIVE_CODEX_POLICY_FILE_ONLY_MODE:
        return validate_live_codex_policy_file_paths(paths)
    if mode == LIVE_CODEX_TESTS_ONLY_MODE:
        return validate_live_codex_tests_only_paths(paths)
    return validate_live_codex_docs_only_paths(paths)


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


def live_codex_tests_only_preflight_checks(
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
    target_path_checks = validate_live_codex_tests_only_paths(target_paths)
    checks = [
        ("project_is_operator", project == "operator"),
        ("worker_is_codex", worker == "codex"),
        ("mode_is_live_codex_tests_only", mode == LIVE_CODEX_TESTS_ONLY_MODE),
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


def live_codex_policy_file_preflight_checks(
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
    target_path_checks = validate_live_codex_policy_file_paths(target_paths)
    checks = [
        ("project_is_operator", project == "operator"),
        ("worker_is_codex", worker == "codex"),
        ("mode_is_live_codex_policy_file_only", mode == LIVE_CODEX_POLICY_FILE_ONLY_MODE),
        ("target_paths_are_policy_allowed", all(check["passed"] for check in target_path_checks)),
        ("repo_root_is_operator_repo", repo_root == get_settings().repo_root.resolve()),
        ("worktree_under_runtime_worktrees", runtime_worktrees in [worktree_resolved, *worktree_resolved.parents]),
        ("canonical_checkout_not_cwd", command_cwd.resolve() != repo_root),
        ("single_live_codex_writer_available", active_delegated_writer_locks == 0),
        ("no_package_install_requested", not any(token in goal_blob for token in ("npm install", "pip install", "apt install", "brew install"))),
        ("no_network_dependent_work", not any(token in goal_blob for token in ("curl ", "wget ", "http://", "https://", "network"))),
        ("no_auto_commit_merge_push", not any(token in goal_blob for token in ("git commit", "git merge", "git push"))),
        ("timeout_is_10_minutes", LIVE_CODEX_TIMEOUT_SECONDS == 600),
        ("max_changed_files_is_1", len(target_paths) == 1),
        ("worktree_exists_or_created", worktree_ready),
        ("preflight_artifact_written", True),
    ]
    return [{"name": name, "passed": bool(passed)} for name, passed in checks] + target_path_checks


def live_codex_model_file_preflight_checks(
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
    target_path_checks = validate_live_codex_model_file_paths(target_paths)
    checks = [
        ("project_is_operator", project == "operator"),
        ("worker_is_codex", worker == "codex"),
        ("mode_is_live_codex_model_file_only", mode == LIVE_CODEX_MODEL_FILE_ONLY_MODE),
        ("target_paths_are_policy_allowed", all(check["passed"] for check in target_path_checks)),
        ("repo_root_is_operator_repo", repo_root == get_settings().repo_root.resolve()),
        ("worktree_under_runtime_worktrees", runtime_worktrees in [worktree_resolved, *worktree_resolved.parents]),
        ("canonical_checkout_not_cwd", command_cwd.resolve() != repo_root),
        ("single_live_codex_writer_available", active_delegated_writer_locks == 0),
        ("no_package_install_requested", not any(token in goal_blob for token in ("npm install", "pip install", "apt install", "brew install"))),
        ("no_network_dependent_work", not any(token in goal_blob for token in ("curl ", "wget ", "http://", "https://", "network"))),
        ("no_auto_commit_merge_push", not any(token in goal_blob for token in ("git commit", "git merge", "git push"))),
        ("timeout_is_10_minutes", LIVE_CODEX_TIMEOUT_SECONDS == 600),
        ("max_changed_files_is_1", len(target_paths) == 1),
        ("worktree_exists_or_created", worktree_ready),
        ("preflight_artifact_written", True),
    ]
    return [{"name": name, "passed": bool(passed)} for name, passed in checks] + target_path_checks


def _live_codex_changed_file_checks(
    *,
    changed_files: list[str],
    path_checks: list[dict],
    count_check: dict,
    allowed_targets: list[str],
) -> list[dict]:
    checks = [
        count_check,
        {
            "name": "changed_files_are_policy_allowed",
            "passed": all(check["passed"] for check in path_checks),
            "details": {"changed_files": changed_files, "allowed": allowed_targets},
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


def validate_live_codex_changed_files(changed_files: list[str]) -> list[dict]:
    path_checks = validate_live_codex_docs_only_paths(changed_files)
    return _live_codex_changed_file_checks(
        changed_files=changed_files,
        path_checks=path_checks,
        count_check={
            "name": "changed_file_count_at_most_5",
            "passed": len(changed_files) <= LIVE_CODEX_MAX_CHANGED_FILES,
            "details": {"count": len(changed_files), "max": LIVE_CODEX_MAX_CHANGED_FILES},
        },
        allowed_targets=live_codex_docs_only_allowed_targets(),
    )


def validate_live_codex_tests_only_changed_files(changed_files: list[str]) -> list[dict]:
    path_checks = validate_live_codex_tests_only_paths(changed_files)
    return _live_codex_changed_file_checks(
        changed_files=changed_files,
        path_checks=path_checks,
        count_check={
            "name": "changed_file_count_at_most_5",
            "passed": len(changed_files) <= LIVE_CODEX_MAX_CHANGED_FILES,
            "details": {"count": len(changed_files), "max": LIVE_CODEX_MAX_CHANGED_FILES},
        },
        allowed_targets=live_codex_tests_only_allowed_targets(),
    )


def validate_live_codex_policy_file_changed_files(changed_files: list[str]) -> list[dict]:
    path_checks = validate_live_codex_policy_file_paths(changed_files)
    return _live_codex_changed_file_checks(
        changed_files=changed_files,
        path_checks=path_checks,
        count_check={
            "name": "changed_file_count_exactly_1",
            "passed": len(changed_files) == 1,
            "details": {"count": len(changed_files), "required": 1},
        },
        allowed_targets=live_codex_policy_file_allowed_targets(),
    )


def validate_live_codex_model_file_changed_files(changed_files: list[str]) -> list[dict]:
    path_checks = validate_live_codex_model_file_paths(changed_files)
    return _live_codex_changed_file_checks(
        changed_files=changed_files,
        path_checks=path_checks,
        count_check={
            "name": "changed_file_count_exactly_1",
            "passed": len(changed_files) == 1,
            "details": {"count": len(changed_files), "required": 1},
        },
        allowed_targets=live_codex_model_file_allowed_targets(),
    )


def _import_root(module_name: str) -> str:
    return module_name.split(".", 1)[0]


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _string_literals(tree: ast.AST) -> list[str]:
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
    return values


def _path_literal_is_allowed(literal: str, allowed_prefixes: list[str]) -> bool:
    return any(literal.startswith(prefix) for prefix in allowed_prefixes)


def _defined_symbols(tree: ast.AST) -> set[str]:
    symbols: set[str] = set()
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            symbols.add(node.target.id)
    return symbols


def _is_exact_frozen_dataclass_decorator(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Name) or node.func.id != "dataclass":
        return False
    if node.args or len(node.keywords) != 1:
        return False
    keyword = node.keywords[0]
    return (
        keyword.arg == "frozen"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
    )


def _exact_frozen_dataclass_classes(tree: ast.AST) -> set[str]:
    classes: set[str] = set()
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if isinstance(node, ast.ClassDef) and any(
            _is_exact_frozen_dataclass_decorator(decorator) for decorator in node.decorator_list
        ):
            classes.add(node.name)
    return classes


def _python_file_content_checks(
    *,
    worktree_path: Path,
    changed_files: list[str],
    path_checks: list[dict],
    check_prefix: str,
    disallowed_import_roots: set[str],
    disallowed_calls: set[str],
    required_symbols: set[str] | None = None,
    required_frozen_dataclasses: set[str] | None = None,
) -> list[dict]:
    path_checks_passed = all(check["passed"] for check in path_checks)
    missing_files: list[str] = []
    syntax_errors: list[dict] = []
    disallowed_imports: list[dict] = []
    disallowed_call_hits: list[dict] = []
    missing_required_symbols: list[dict] = []
    missing_frozen_dataclasses: list[dict] = []

    if path_checks_passed:
        for changed_file in changed_files:
            file_path = worktree_path / changed_file
            if not file_path.exists():
                missing_files.append(changed_file)
                continue
            try:
                source = file_path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=changed_file)
            except SyntaxError as exc:
                syntax_errors.append({"path": changed_file, "line": exc.lineno, "message": exc.msg})
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = _import_root(alias.name)
                        if root in disallowed_import_roots:
                            disallowed_imports.append({"path": changed_file, "module": alias.name, "line": node.lineno})
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root = _import_root(node.module)
                    if root in disallowed_import_roots:
                        disallowed_imports.append({"path": changed_file, "module": node.module, "line": node.lineno})
                elif isinstance(node, ast.Call):
                    call_name = _call_name(node.func)
                    if call_name in disallowed_calls:
                        disallowed_call_hits.append({"path": changed_file, "call": call_name, "line": node.lineno})

            if required_symbols is not None:
                defined_symbols = _defined_symbols(tree)
                missing = sorted(required_symbols - defined_symbols)
                if missing:
                    missing_required_symbols.append({"path": changed_file, "missing_symbols": missing})

            if required_frozen_dataclasses is not None:
                frozen_dataclass_classes = _exact_frozen_dataclass_classes(tree)
                missing = sorted(required_frozen_dataclasses - frozen_dataclass_classes)
                if missing:
                    missing_frozen_dataclasses.append({"path": changed_file, "missing_frozen_dataclasses": missing})

    return [
        {
            "name": f"{check_prefix}_paths_are_valid",
            "passed": path_checks_passed,
            "details": {"changed_files": changed_files},
        },
        {
            "name": f"{check_prefix}_files_exist",
            "passed": not missing_files,
            "details": {"missing_files": missing_files},
        },
        {
            "name": f"{check_prefix}_is_python_parseable",
            "passed": not syntax_errors,
            "details": {"syntax_errors": syntax_errors},
        },
        {
            "name": f"{check_prefix}_imports_are_allowed",
            "passed": not disallowed_imports,
            "details": {"disallowed_imports": disallowed_imports, "disallowed_import_roots": sorted(disallowed_import_roots)},
        },
        {
            "name": f"{check_prefix}_calls_are_allowed",
            "passed": not disallowed_call_hits,
            "details": {"disallowed_calls": disallowed_call_hits, "blocked_calls": sorted(disallowed_calls)},
        },
        {
            "name": f"{check_prefix}_required_symbols_exist",
            "passed": not missing_required_symbols,
            "details": {
                "missing_required_symbols": missing_required_symbols,
                "required_symbols": sorted(required_symbols or set()),
            },
        },
        {
            "name": f"{check_prefix}_required_frozen_dataclasses_exist",
            "passed": not missing_frozen_dataclasses,
            "details": {
                "missing_frozen_dataclasses": missing_frozen_dataclasses,
                "required_frozen_dataclasses": sorted(required_frozen_dataclasses or set()),
            },
        },
    ]


def validate_live_codex_tests_only_content(worktree_path: Path, changed_files: list[str]) -> list[dict]:
    path_checks = validate_live_codex_tests_only_paths(changed_files)
    path_checks_passed = all(check["passed"] for check in path_checks)
    disallowed_import_roots = set(live_codex_tests_only_disallowed_import_roots())
    disallowed_calls = set(live_codex_tests_only_disallowed_calls())
    disallowed_string_tokens = live_codex_tests_only_disallowed_string_tokens()
    disallowed_path_prefixes = live_codex_tests_only_disallowed_path_prefixes()
    allowed_path_prefixes = live_codex_tests_only_allowed_path_prefixes()
    disallowed_host_literals = live_codex_tests_only_disallowed_host_literals()

    missing_files: list[str] = []
    syntax_errors: list[dict] = []
    disallowed_imports: list[dict] = []
    disallowed_call_hits: list[dict] = []
    disallowed_string_hits: list[dict] = []
    disallowed_path_hits: list[dict] = []
    disallowed_host_hits: list[dict] = []

    if path_checks_passed:
        for changed_file in changed_files:
            file_path = worktree_path / changed_file
            if not file_path.exists():
                missing_files.append(changed_file)
                continue
            try:
                source = file_path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=changed_file)
            except SyntaxError as exc:
                syntax_errors.append({"path": changed_file, "line": exc.lineno, "message": exc.msg})
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = _import_root(alias.name)
                        if root in disallowed_import_roots:
                            disallowed_imports.append({"path": changed_file, "module": alias.name, "line": node.lineno})
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root = _import_root(node.module)
                    if root in disallowed_import_roots:
                        disallowed_imports.append({"path": changed_file, "module": node.module, "line": node.lineno})
                elif isinstance(node, ast.Call):
                    call_name = _call_name(node.func)
                    if call_name in disallowed_calls:
                        disallowed_call_hits.append({"path": changed_file, "call": call_name, "line": node.lineno})

            for literal in _string_literals(tree):
                lowered = literal.lower()
                for token in disallowed_string_tokens:
                    if token.lower() in lowered:
                        disallowed_string_hits.append({"path": changed_file, "token": token, "literal": literal})
                for prefix in disallowed_path_prefixes:
                    if literal.startswith(prefix) and not _path_literal_is_allowed(literal, allowed_path_prefixes):
                        disallowed_path_hits.append({"path": changed_file, "prefix": prefix, "literal": literal})
                for host in disallowed_host_literals:
                    if host.lower() in lowered:
                        disallowed_host_hits.append({"path": changed_file, "host": host, "literal": literal})

    return [
        {
            "name": "test_content_paths_are_valid",
            "passed": path_checks_passed,
            "details": {"changed_files": changed_files},
        },
        {
            "name": "test_content_files_exist",
            "passed": not missing_files,
            "details": {"missing_files": missing_files},
        },
        {
            "name": "test_content_is_python_parseable",
            "passed": not syntax_errors,
            "details": {"syntax_errors": syntax_errors},
        },
        {
            "name": "test_content_imports_are_allowed",
            "passed": not disallowed_imports,
            "details": {"disallowed_imports": disallowed_imports, "disallowed_import_roots": sorted(disallowed_import_roots)},
        },
        {
            "name": "test_content_calls_are_allowed",
            "passed": not disallowed_call_hits,
            "details": {"disallowed_calls": disallowed_call_hits, "blocked_calls": sorted(disallowed_calls)},
        },
        {
            "name": "test_content_has_no_live_command_literals",
            "passed": not disallowed_string_hits,
            "details": {"disallowed_strings": disallowed_string_hits, "blocked_tokens": disallowed_string_tokens},
        },
        {
            "name": "test_content_has_no_production_path_literals",
            "passed": not disallowed_path_hits,
            "details": {
                "disallowed_paths": disallowed_path_hits,
                "blocked_prefixes": disallowed_path_prefixes,
                "allowed_prefixes": allowed_path_prefixes,
            },
        },
        {
            "name": "test_content_has_no_live_host_literals",
            "passed": not disallowed_host_hits,
            "details": {"disallowed_hosts": disallowed_host_hits, "blocked_hosts": disallowed_host_literals},
        },
    ]


def validate_live_codex_policy_file_content(worktree_path: Path, changed_files: list[str]) -> list[dict]:
    return _python_file_content_checks(
        worktree_path=worktree_path,
        changed_files=changed_files,
        path_checks=validate_live_codex_policy_file_paths(changed_files),
        check_prefix="policy_file_content",
        disallowed_import_roots=set(live_codex_policy_file_disallowed_import_roots()),
        disallowed_calls=set(live_codex_policy_file_disallowed_calls()),
        required_symbols=set(live_codex_policy_file_required_symbols()),
    )


def validate_live_codex_model_file_content(worktree_path: Path, changed_files: list[str]) -> list[dict]:
    return _python_file_content_checks(
        worktree_path=worktree_path,
        changed_files=changed_files,
        path_checks=validate_live_codex_model_file_paths(changed_files),
        check_prefix="model_file_content",
        disallowed_import_roots=set(live_codex_model_file_disallowed_import_roots()),
        disallowed_calls=set(live_codex_model_file_disallowed_calls()),
        required_symbols=set(live_codex_model_file_required_symbols()),
        required_frozen_dataclasses=set(live_codex_model_file_required_frozen_dataclasses()),
    )


def validate_live_codex_changed_files_for_mode(mode: str, changed_files: list[str]) -> list[dict]:
    if mode == LIVE_CODEX_MODEL_FILE_ONLY_MODE:
        return validate_live_codex_model_file_changed_files(changed_files)
    if mode == LIVE_CODEX_POLICY_FILE_ONLY_MODE:
        return validate_live_codex_policy_file_changed_files(changed_files)
    if mode == LIVE_CODEX_TESTS_ONLY_MODE:
        return validate_live_codex_tests_only_changed_files(changed_files)
    return validate_live_codex_changed_files(changed_files)
