from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings


ALLOWED_AGENTS = {"codex", "claude_code", "n8n"}
DEPLOYMENT_METHODS = {"none", "manual", "siteground_sftp", "droplet_systemd", "docker_compose", "n8n_webhook"}
PROJECT_STATUSES = {"active", "paused", "planned", "archived"}
REQUIRED_PROJECT_FIELDS = {
    "slug",
    "name",
    "repo_path",
    "stack",
    "domains",
    "services",
    "allowed_agents",
    "deployment_method",
    "status",
    "notes",
}

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
HOSTNAME_PATTERN = re.compile(r"^(?=.{1,253}$)([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)(\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(api[_-]?key|access[_-]?token|secret|password)\s*[:=]", re.IGNORECASE),
    re.compile(r"\b(sk|pk)_(live|test)_[A-Za-z0-9]+"),
)


@dataclass(frozen=True)
class ProjectRegistryValidation:
    ok: bool
    errors: list[str]


def projects_registry_path() -> Path:
    return get_settings().repo_root / "registry" / "projects.yaml"


def load_projects(path: Path | None = None) -> dict[str, dict[str, Any]]:
    registry_path = path or projects_registry_path()
    raw_data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, dict):
        raise ValueError("registry root must be a mapping")
    projects = raw_data.get("projects")
    if not isinstance(projects, dict):
        raise ValueError("registry must contain a projects mapping")
    return projects


def validate_projects(projects: dict[str, dict[str, Any]]) -> ProjectRegistryValidation:
    errors: list[str] = []
    for project_key, project in projects.items():
        prefix = f"projects.{project_key}"
        if not isinstance(project_key, str) or not SLUG_PATTERN.fullmatch(project_key):
            errors.append(f"{prefix}: project key must be lowercase and safe")
        if not isinstance(project, dict):
            errors.append(f"{prefix}: project must be a mapping")
            continue

        missing_fields = sorted(REQUIRED_PROJECT_FIELDS - set(project))
        for field in missing_fields:
            errors.append(f"{prefix}: missing required field {field}")

        slug = project.get("slug")
        if slug != project_key:
            errors.append(f"{prefix}: slug must match project key")
        if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
            errors.append(f"{prefix}.slug: must be lowercase and safe")

        _validate_nonempty_string(project, "name", prefix, errors)
        _validate_nonempty_string(project, "repo_path", prefix, errors)
        _validate_string_list(project, "stack", prefix, errors, allow_empty=False)
        _validate_string_list(project, "services", prefix, errors, allow_empty=True)
        _validate_agents(project, prefix, errors)
        _validate_deployment_method(project, prefix, errors)
        _validate_status(project, prefix, errors)
        _validate_nonempty_string(project, "notes", prefix, errors)
        _validate_domains(project, prefix, errors)
        _validate_no_secret_values(project, prefix, errors)

    return ProjectRegistryValidation(ok=not errors, errors=errors)


def validate_registry(path: Path | None = None) -> ProjectRegistryValidation:
    try:
        projects = load_projects(path)
    except Exception as exc:
        return ProjectRegistryValidation(ok=False, errors=[str(exc)])
    return validate_projects(projects)


def ordered_projects(projects: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return list(projects.values())


def get_project(slug: str, path: Path | None = None) -> dict[str, Any]:
    projects = load_projects(path)
    try:
        return projects[slug]
    except KeyError as exc:
        raise KeyError(f"unknown project: {slug}") from exc


def _validate_nonempty_string(project: dict[str, Any], field: str, prefix: str, errors: list[str]) -> None:
    value = project.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{prefix}.{field}: must be a non-empty string")


def _validate_string_list(
    project: dict[str, Any],
    field: str,
    prefix: str,
    errors: list[str],
    *,
    allow_empty: bool,
) -> None:
    value = project.get(field)
    if not isinstance(value, list):
        errors.append(f"{prefix}.{field}: must be a list")
        return
    if not allow_empty and not value:
        errors.append(f"{prefix}.{field}: must not be empty")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{prefix}.{field}: entries must be non-empty strings")


def _validate_agents(project: dict[str, Any], prefix: str, errors: list[str]) -> None:
    value = project.get("allowed_agents")
    if not isinstance(value, list) or not value:
        errors.append(f"{prefix}.allowed_agents: must be a non-empty list")
        return
    for agent in value:
        if agent not in ALLOWED_AGENTS:
            errors.append(f"{prefix}.allowed_agents: unknown agent {agent!r}")


def _validate_deployment_method(project: dict[str, Any], prefix: str, errors: list[str]) -> None:
    value = project.get("deployment_method")
    if value not in DEPLOYMENT_METHODS:
        errors.append(f"{prefix}.deployment_method: unknown deployment method {value!r}")


def _validate_status(project: dict[str, Any], prefix: str, errors: list[str]) -> None:
    value = project.get("status")
    if value not in PROJECT_STATUSES:
        errors.append(f"{prefix}.status: unknown status {value!r}")


def _validate_domains(project: dict[str, Any], prefix: str, errors: list[str]) -> None:
    domains = project.get("domains")
    if not isinstance(domains, list):
        errors.append(f"{prefix}.domains: must be a list")
        return
    for domain in domains:
        if not isinstance(domain, str) or not domain.strip():
            errors.append(f"{prefix}.domains: entries must be non-empty strings")
            continue
        if "://" in domain or "/" in domain or "@" in domain or ":" in domain:
            errors.append(f"{prefix}.domains: {domain!r} must be a hostname only")
            continue
        if not HOSTNAME_PATTERN.fullmatch(domain):
            errors.append(f"{prefix}.domains: {domain!r} must be a valid hostname")


def _validate_no_secret_values(project: dict[str, Any], prefix: str, errors: list[str]) -> None:
    for field_path, value in _walk_values(project):
        if isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_PATTERNS):
            errors.append(f"{prefix}.{field_path}: must not contain secret or credential values")


def _walk_values(value: Any, path: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        values: list[tuple[str, Any]] = []
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            values.extend(_walk_values(item, child_path))
        return values
    if isinstance(value, list):
        values = []
        for index, item in enumerate(value):
            child_path = f"{path}[{index}]"
            values.extend(_walk_values(item, child_path))
        return values
    return [(path, value)]
