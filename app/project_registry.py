from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings
from tools.git_tools import git_head, git_is_inside_work_tree, git_status_porcelain, git_top_level, slugify


ALLOWED_AGENTS = {"codex", "claude_code", "gemini_cli", "n8n"}
ALLOWED_WRITE_AGENTS = {"codex", "claude_code"}
ALLOWED_WRITE_LANES = {"docs_only", "tests_only", "single_file_code", "multi_file_scoped", "scaffold_only"}
DEPLOYMENT_METHODS = {"none", "manual", "siteground_sftp", "droplet_systemd", "docker_compose", "n8n_webhook"}
PROJECT_STATUSES = {"active", "paused", "planned", "archived"}
REQUIRED_WRITE_POLICY_FIELDS = {
    "writable",
    "allowed_write_agents",
    "allowed_lane",
    "max_changed_files",
    "allow_file_creation",
    "requires_human_approval",
    "deployment_allowed",
}
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
PROJECT_CONTEXT_SOURCE = "registry/projects.yaml"

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


@dataclass(frozen=True)
class ExternalWritePreflightResult:
    result_code: str
    authorized: bool
    requested_project: str
    requested_worker: str
    requested_lane: str
    project: dict[str, Any] | None
    write_policy: dict[str, Any]
    reasons: list[str]
    next_actions: list[str]


@dataclass(frozen=True)
class ExternalWorktreeDryRunResult:
    result_code: str
    safe: bool
    preflight: ExternalWritePreflightResult
    project: dict[str, Any] | None
    repo_checks: dict[str, Any]
    worktree_plan: dict[str, Any]
    reasons: list[str]
    next_actions: list[str]


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
        _validate_write_policy(project, prefix, errors)
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
        raise KeyError(f"Unknown project slug: {slug}\nRun scripts/operator projects list to see known projects.") from exc


def preflight_project_write(
    slug: str,
    *,
    worker: str,
    lane: str,
    path: Path | None = None,
) -> ExternalWritePreflightResult:
    projects = load_projects(path)
    project = projects.get(slug)
    if project is None:
        return ExternalWritePreflightResult(
            result_code="unknown_project",
            authorized=False,
            requested_project=slug,
            requested_worker=worker,
            requested_lane=lane,
            project=None,
            write_policy=_default_non_writable_policy(),
            reasons=[f"Project slug {slug!r} is not in registry/projects.yaml."],
            next_actions=["Add the project to registry/projects.yaml before requesting external write preflight."],
        )

    raw_write_policy = project.get("write_policy")
    if not isinstance(raw_write_policy, dict):
        return ExternalWritePreflightResult(
            result_code="known_non_writable",
            authorized=False,
            requested_project=slug,
            requested_worker=worker,
            requested_lane=lane,
            project=project,
            write_policy=_default_non_writable_policy(),
            reasons=[
                "Project is known in registry/projects.yaml.",
                "write_policy is absent; absent policy is treated as non-writable.",
                "No external write lane is authorized for this project.",
            ],
            next_actions=[
                "Leave blocked, or update registry/projects.yaml write_policy in a future explicit policy phase.",
            ],
        )

    write_policy = dict(raw_write_policy)
    if write_policy.get("writable") is not True:
        return ExternalWritePreflightResult(
            result_code="known_non_writable",
            authorized=False,
            requested_project=slug,
            requested_worker=worker,
            requested_lane=lane,
            project=project,
            write_policy=write_policy,
            reasons=[
                "Project is known in registry/projects.yaml.",
                "write_policy.writable is false.",
                "No external write lane is authorized for this project.",
            ],
            next_actions=[
                "Leave blocked, or update registry/projects.yaml write_policy in a future explicit policy phase.",
            ],
        )

    reasons: list[str] = []
    allowed_agents = project.get("allowed_agents") if isinstance(project.get("allowed_agents"), list) else []
    allowed_write_agents = (
        write_policy.get("allowed_write_agents") if isinstance(write_policy.get("allowed_write_agents"), list) else []
    )
    allowed_lane = write_policy.get("allowed_lane")
    allowed_lanes = allowed_lane if isinstance(allowed_lane, list) else [allowed_lane]

    if worker not in allowed_agents:
        reasons.append(f"Requested worker {worker} is not in project allowed_agents.")
    if worker not in allowed_write_agents:
        reasons.append(f"Requested worker {worker} is not in write_policy.allowed_write_agents.")
    if lane not in allowed_lanes:
        reasons.append(f"Requested lane {lane} does not match write_policy.allowed_lane {_format_policy_value(allowed_lane)}.")
    if write_policy.get("deployment_allowed") is True:
        reasons.append("write_policy.deployment_allowed is true, but Phase 2.10b never performs deployment.")

    if reasons:
        return ExternalWritePreflightResult(
            result_code="writable_no_lane_authorized",
            authorized=False,
            requested_project=slug,
            requested_worker=worker,
            requested_lane=lane,
            project=project,
            write_policy=write_policy,
            reasons=reasons,
            next_actions=[
                "Review registry/projects.yaml write_policy before requesting a later external dry-run phase.",
            ],
        )

    return ExternalWritePreflightResult(
        result_code="writable_lane_authorized",
        authorized=True,
        requested_project=slug,
        requested_worker=worker,
        requested_lane=lane,
        project=project,
        write_policy=write_policy,
        reasons=[
            "Project is known in registry/projects.yaml.",
            "write_policy.writable is true.",
            "Policy allows this worker/lane combination.",
        ],
        next_actions=[
            "This is preflight-only. No worktree, worker launch, promotion, or deployment occurred.",
        ],
    )


def dry_run_external_worktree(
    slug: str,
    *,
    worker: str,
    lane: str,
    path: Path | None = None,
) -> ExternalWorktreeDryRunResult:
    preflight = preflight_project_write(slug, worker=worker, lane=lane, path=path)
    if not preflight.authorized:
        return ExternalWorktreeDryRunResult(
            result_code="policy_blocked",
            safe=False,
            preflight=preflight,
            project=preflight.project,
            repo_checks={},
            worktree_plan={},
            reasons=["External write preflight did not authorize this request.", *preflight.reasons],
            next_actions=preflight.next_actions,
        )

    project = preflight.project
    if project is None:
        return ExternalWorktreeDryRunResult(
            result_code="policy_blocked",
            safe=False,
            preflight=preflight,
            project=None,
            repo_checks={},
            worktree_plan={},
            reasons=["Project context is unavailable after external write preflight."],
            next_actions=["Rerun scripts/operator projects validate and retry."],
        )

    settings = get_settings()
    repo_path = Path(project["repo_path"])
    repo_resolved = repo_path.resolve()
    operator_root = settings.repo_root.resolve()

    unsafe_reasons: list[str] = []
    if slug != "operator":
        if repo_resolved == operator_root:
            unsafe_reasons.append("External canonical repo must not be the Operator repo.")
        if operator_root in repo_resolved.parents:
            unsafe_reasons.append("External canonical repo must not be inside the Operator repo.")
    if unsafe_reasons:
        return _blocked_worktree_dry_run(
            "canonical_repo_unsafe_path",
            preflight=preflight,
            project=project,
            repo_checks={"repo_path": str(repo_path), "repo_path_resolved": str(repo_resolved)},
            reasons=unsafe_reasons,
            next_actions=["Use the canonical repo path recorded in registry/projects.yaml, outside the Operator checkout."],
        )

    if not repo_path.exists():
        return _blocked_worktree_dry_run(
            "canonical_repo_missing",
            preflight=preflight,
            project=project,
            repo_checks={"repo_path": str(repo_path), "exists": False},
            reasons=["repo_path does not exist."],
            next_actions=["Create or clone the canonical repo at the registry repo_path, then rerun this dry-run."],
        )
    if not repo_path.is_dir():
        return _blocked_worktree_dry_run(
            "canonical_repo_missing",
            preflight=preflight,
            project=project,
            repo_checks={"repo_path": str(repo_path), "exists": True, "is_directory": False},
            reasons=["repo_path is not a directory."],
            next_actions=["Fix registry/projects.yaml repo_path or replace it with a git repository directory."],
        )

    inside_result = git_is_inside_work_tree(repo_path=repo_path)
    top_level_result = git_top_level(repo_path=repo_path)
    head_result = git_head(worktree_path=repo_path)
    repo_checks: dict[str, Any] = {
        "repo_path": str(repo_path),
        "repo_path_resolved": str(repo_resolved),
        "exists": True,
        "is_directory": True,
        "is_git_work_tree": inside_result.stdout.strip(),
        "git_top_level": top_level_result.stdout.strip(),
        "head": head_result.stdout.strip(),
    }
    if inside_result.exit_code != 0 or inside_result.stdout.strip() != "true":
        return _blocked_worktree_dry_run(
            "canonical_repo_not_git",
            preflight=preflight,
            project=project,
            repo_checks=repo_checks,
            reasons=["repo_path is not a git work tree."],
            next_actions=["Initialize or clone a git repository at repo_path, then rerun this dry-run."],
        )
    if top_level_result.exit_code != 0 or Path(top_level_result.stdout.strip()).resolve() != repo_resolved:
        return _blocked_worktree_dry_run(
            "canonical_repo_not_git",
            preflight=preflight,
            project=project,
            repo_checks=repo_checks,
            reasons=["git top-level does not resolve to repo_path."],
            next_actions=["Point registry/projects.yaml repo_path at the canonical git repository root."],
        )
    if head_result.exit_code != 0 or not head_result.stdout.strip():
        return _blocked_worktree_dry_run(
            "canonical_repo_not_git",
            preflight=preflight,
            project=project,
            repo_checks=repo_checks,
            reasons=["git HEAD could not be resolved."],
            next_actions=["Create an initial commit in the canonical repo, then rerun this dry-run."],
        )

    status_result = git_status_porcelain(repo_path=repo_path)
    repo_checks["status_porcelain"] = status_result.stdout
    if status_result.exit_code != 0:
        return _blocked_worktree_dry_run(
            "canonical_repo_not_git",
            preflight=preflight,
            project=project,
            repo_checks=repo_checks,
            reasons=["git status --porcelain failed."],
            next_actions=["Inspect the canonical repo manually, then rerun this dry-run."],
        )
    if status_result.stdout.strip():
        return _blocked_worktree_dry_run(
            "canonical_repo_dirty",
            preflight=preflight,
            project=project,
            repo_checks=repo_checks,
            reasons=["Canonical repo has uncommitted changes."],
            next_actions=["Review and commit, stash, or discard canonical repo changes before external worktree dry-run can pass."],
        )

    worktree_plan = _external_worktree_plan(slug=slug, worker=worker, lane=lane, repo_path=repo_path)
    if not worktree_plan["worktree_path_under_runtime_worktrees"]:
        return _blocked_worktree_dry_run(
            "canonical_repo_unsafe_path",
            preflight=preflight,
            project=project,
            repo_checks=repo_checks,
            worktree_plan=worktree_plan,
            reasons=["Intended worktree path is not under Operator runtime/worktrees."],
            next_actions=["Fix Operator runtime configuration before attempting external worktree creation."],
        )
    if Path(worktree_plan["worktree_path"]).exists():
        return _blocked_worktree_dry_run(
            "worktree_path_collision",
            preflight=preflight,
            project=project,
            repo_checks=repo_checks,
            worktree_plan=worktree_plan,
            reasons=["Intended worktree path already exists."],
            next_actions=["Remove or choose a different external worktree dry-run path in a later explicit phase."],
        )

    return ExternalWorktreeDryRunResult(
        result_code="dry_run_safe",
        safe=True,
        preflight=preflight,
        project=project,
        repo_checks=repo_checks,
        worktree_plan=worktree_plan,
        reasons=["Dry-run passed; worktree creation would be safe to attempt in a later phase."],
        next_actions=["No worktree was created. No worker was launched. No patch was promoted. No deployment occurred."],
    )


def project_context_for_task(slug: str, path: Path | None = None) -> dict[str, Any]:
    validation = validate_registry(path)
    if not validation.ok:
        raise ValueError("project registry is invalid; run scripts/operator projects validate")
    projects = load_projects(path)
    project = projects.get(slug)
    if project is None:
        raise ValueError(f"Unknown project slug: {slug}\nRun scripts/operator projects list to see known projects.")
    return {
        "project_context": {
            "slug": project["slug"],
            "name": project["name"],
            "repo_path": project["repo_path"],
            "stack": list(project["stack"]),
            "domains": list(project["domains"]),
            "services": list(project["services"]),
            "allowed_agents": list(project["allowed_agents"]),
            "deployment_method": project["deployment_method"],
            "status": project["status"],
            "notes": project["notes"],
        },
        "project_context_source": PROJECT_CONTEXT_SOURCE,
    }


def _default_non_writable_policy() -> dict[str, Any]:
    return {
        "writable": False,
        "allowed_write_agents": [],
        "allowed_lane": None,
        "max_changed_files": 1,
        "allow_file_creation": False,
        "requires_human_approval": True,
        "deployment_allowed": False,
    }


def _format_policy_value(value: Any) -> str:
    return "null" if value is None else str(value)


def _blocked_worktree_dry_run(
    result_code: str,
    *,
    preflight: ExternalWritePreflightResult,
    project: dict[str, Any] | None,
    repo_checks: dict[str, Any],
    reasons: list[str],
    next_actions: list[str],
    worktree_plan: dict[str, Any] | None = None,
) -> ExternalWorktreeDryRunResult:
    return ExternalWorktreeDryRunResult(
        result_code=result_code,
        safe=False,
        preflight=preflight,
        project=project,
        repo_checks=repo_checks,
        worktree_plan=worktree_plan or {},
        reasons=reasons,
        next_actions=next_actions,
    )


def _external_worktree_plan(*, slug: str, worker: str, lane: str, repo_path: Path) -> dict[str, Any]:
    settings = get_settings()
    worktree_path = settings.worktrees_dir / "external" / slug / worker / lane
    resolved_worktree_path = worktree_path.resolve()
    runtime_worktrees = settings.worktrees_dir.resolve()
    branch_name = f"operator/external/{slugify(slug)}/{slugify(worker)}/{slugify(lane)}"
    intended_command = (
        f"git -C {repo_path} worktree add -B {branch_name} {worktree_path} HEAD"
    )
    return {
        "worktree_path": str(worktree_path),
        "worktree_path_resolved": str(resolved_worktree_path),
        "worktree_path_under_runtime_worktrees": runtime_worktrees in [resolved_worktree_path, *resolved_worktree_path.parents],
        "worktree_path_exists": worktree_path.exists(),
        "branch_name": branch_name,
        "intended_command": intended_command,
        "command_ran": False,
    }


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


def _validate_write_policy(project: dict[str, Any], prefix: str, errors: list[str]) -> None:
    if "write_policy" not in project:
        return

    write_policy = project.get("write_policy")
    policy_prefix = f"{prefix}.write_policy"
    if not isinstance(write_policy, dict):
        errors.append(f"{policy_prefix}: must be a mapping")
        return

    writable = write_policy.get("writable")
    if not isinstance(writable, bool):
        errors.append(f"{policy_prefix}.writable: must be a boolean")
        return

    if writable:
        missing_fields = sorted(REQUIRED_WRITE_POLICY_FIELDS - set(write_policy))
        for field in missing_fields:
            errors.append(f"{policy_prefix}: missing required field {field}")

    unknown_fields = sorted(set(write_policy) - REQUIRED_WRITE_POLICY_FIELDS)
    for field in unknown_fields:
        errors.append(f"{policy_prefix}.{field}: unknown field")

    _validate_allowed_write_agents(project, write_policy, policy_prefix, errors)
    _validate_allowed_lane(write_policy, policy_prefix, errors)
    _validate_optional_positive_int(write_policy, "max_changed_files", policy_prefix, errors)
    _validate_optional_bool(write_policy, "allow_file_creation", policy_prefix, errors)
    _validate_optional_bool(write_policy, "requires_human_approval", policy_prefix, errors)
    _validate_optional_bool(write_policy, "deployment_allowed", policy_prefix, errors)

    if write_policy.get("deployment_allowed") is True:
        errors.append(f"{policy_prefix}.deployment_allowed: true is not allowed in Phase 2.10a")
    if writable and "deployment_allowed" not in write_policy:
        errors.append(f"{policy_prefix}.deployment_allowed: must be explicit for writable projects")


def _validate_allowed_write_agents(
    project: dict[str, Any],
    write_policy: dict[str, Any],
    policy_prefix: str,
    errors: list[str],
) -> None:
    if "allowed_write_agents" not in write_policy:
        return
    value = write_policy.get("allowed_write_agents")
    if not isinstance(value, list):
        errors.append(f"{policy_prefix}.allowed_write_agents: must be a list")
        return

    allowed_agents = project.get("allowed_agents")
    allowed_agent_set = set(allowed_agents) if isinstance(allowed_agents, list) else set()
    for agent in value:
        if not isinstance(agent, str) or not agent.strip():
            errors.append(f"{policy_prefix}.allowed_write_agents: entries must be non-empty strings")
            continue
        if agent not in ALLOWED_WRITE_AGENTS:
            errors.append(f"{policy_prefix}.allowed_write_agents: unknown write agent {agent!r}")
            continue
        if agent not in allowed_agent_set:
            errors.append(f"{policy_prefix}.allowed_write_agents: write agent {agent!r} must also appear in allowed_agents")


def _validate_allowed_lane(write_policy: dict[str, Any], policy_prefix: str, errors: list[str]) -> None:
    if "allowed_lane" not in write_policy:
        return
    value = write_policy.get("allowed_lane")
    if value is None:
        return
    if isinstance(value, list):
        if not value:
            errors.append(f"{policy_prefix}.allowed_lane: must not be empty")
            return
        for lane in value:
            if not isinstance(lane, str):
                errors.append(f"{policy_prefix}.allowed_lane: entries must be strings")
                continue
            if lane not in ALLOWED_WRITE_LANES:
                errors.append(f"{policy_prefix}.allowed_lane: unknown lane {lane!r}")
        return
    if not isinstance(value, str):
        errors.append(f"{policy_prefix}.allowed_lane: must be null, a string, or a list of strings")
        return
    if value not in ALLOWED_WRITE_LANES:
        errors.append(f"{policy_prefix}.allowed_lane: unknown lane {value!r}")


def _validate_optional_bool(write_policy: dict[str, Any], field: str, policy_prefix: str, errors: list[str]) -> None:
    if field in write_policy and not isinstance(write_policy.get(field), bool):
        errors.append(f"{policy_prefix}.{field}: must be a boolean")


def _validate_optional_positive_int(write_policy: dict[str, Any], field: str, policy_prefix: str, errors: list[str]) -> None:
    if field not in write_policy:
        return
    value = write_policy.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        errors.append(f"{policy_prefix}.{field}: must be a positive integer")


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
