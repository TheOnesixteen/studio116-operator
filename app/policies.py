from __future__ import annotations

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
