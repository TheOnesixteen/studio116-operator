from __future__ import annotations

import os
from typing import Any


def resolve_project_from_cwd(cwd: str, projects: dict[str, Any]) -> str | None:
    """
    Given a current working directory and the loaded projects dict (slug -> project),
    return the project slug whose repo_path is a prefix of cwd.
    Picks the longest matching prefix to handle nested repos.
    Returns None if no match found.
    """
    cwd_resolved = os.path.realpath(cwd)
    best_match: str | None = None
    best_length = 0

    for slug, project in projects.items():
        repo_path = project.get("repo_path", "")
        if not repo_path:
            continue
        repo_resolved = os.path.realpath(repo_path)
        if cwd_resolved == repo_resolved or cwd_resolved.startswith(repo_resolved + os.sep):
            if len(repo_resolved) > best_length:
                best_match = slug
                best_length = len(repo_resolved)

    return best_match


def snapshot_blocked_paths(project_slug: str, policies: dict[str, Any]) -> list[str]:
    """
    Pull forbidden_paths and blocked_paths from policies.yaml for this project
    at compile time. These are baked into the StandardizedTask so the engine
    has an unalterable blacklist. Falls back to a safe default set if those
    sections are absent from the policy file.
    """
    blocked: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        if path and path not in seen:
            blocked.append(path)
            seen.add(path)

    # Pull from explicit forbidden_paths or blocked_paths sections if they exist
    for section in ("forbidden_paths", "blocked_paths"):
        entries = policies.get(section, [])
        if isinstance(entries, list):
            for entry in entries:
                _add(str(entry))

    # Default dangerous path patterns derived from the policy engine's logic
    defaults = [
        ".env",
        "*.env",
        ".env.*",
        "**/.env",
        "**/secrets*",
        "**/*.pem",
        "**/*.key",
        "**/caddy*",
        "**/docker-compose*",
        "**/compose.yaml",
        "**/compose.yml",
        "**/*.service",
        "**/systemd*",
        "**/nginx.conf",
        "**/firewall*",
    ]
    for path in defaults:
        _add(path)

    return blocked


def normalize_target_paths(paths: list[str], origin_dir: str, repo_path: str | None = None) -> list[str]:
    """
    Resolve all relative paths against origin_dir using os.path.realpath.
    Reject any path that resolves outside the project repo_path when repo_path
    is provided. Returns the resolved absolute paths that pass validation.
    """
    resolved: list[str] = []
    origin_resolved = os.path.realpath(origin_dir)

    for path in paths:
        if os.path.isabs(path):
            candidate = os.path.realpath(path)
        else:
            candidate = os.path.realpath(os.path.join(origin_resolved, path))

        if repo_path:
            repo_resolved = os.path.realpath(repo_path)
            if candidate != repo_resolved and not candidate.startswith(repo_resolved + os.sep):
                continue  # Reject paths outside repo

        resolved.append(candidate)

    return resolved
