from __future__ import annotations

import os
import sys
from typing import Any

from app.models import StandardizedTask
from app.intake.context_resolver import resolve_project_from_cwd
from app.intake.risk_scorer import score_risk
from app.intake.normalizer import select_normalizer, normalize_task, display_task


def _is_top_level_cwd(cwd: str) -> bool:
    """Return True if cwd is a top-level system directory (not a project dir)."""
    top_level_dirs = {"/", "/root", "/home", "/tmp", "/var", "/etc", "/opt"}
    return os.path.realpath(cwd) in top_level_dirs


def _has_wide_scope(raw_input: str) -> bool:
    """Return True if the raw input suggests a dangerously broad scope."""
    return "*" in raw_input or "**" in raw_input


def parse_adhoc(
    raw_input: str,
    cwd: str,
    *,
    project_override: str | None = None,
    agent_override: str | None = None,
    dry_run: bool = False,
    skip_confirmation: bool = False,
) -> StandardizedTask:
    """
    Parse a plain-English quick task from `operator do "<goal>"`.

    Steps:
    1. Resolve project from cwd (or use --project override)
    2. Score risk and detect wide scope
    3. Select normalization level
    4. Call appropriate normalizer (local/codex/claude)
    5. Display interpreted task to user
    6. Wait for confirmation if required
    7. Return StandardizedTask with source_context.entrypoint = "do"

    Raises ValueError if project cannot be inferred and no --project flag given.
    Raises SystemExit if the user cancels at the confirmation prompt.
    """
    import yaml
    from app.config import get_settings
    from app.policies import load_policy_registry
    from app.project_registry import load_projects

    # --- Load registries ---
    try:
        projects = load_projects()
    except Exception as exc:
        raise RuntimeError(f"Failed to load project registry: {exc}") from exc

    try:
        policies = load_policy_registry()
    except Exception as exc:
        raise RuntimeError(f"Failed to load policy registry: {exc}") from exc

    # --- 1. Resolve project ---
    if project_override:
        project = project_override.lower().strip()
        # Validate the slug exists in the registry
        if project not in projects:
            known = ", ".join(sorted(projects.keys()))
            raise ValueError(
                f"Unknown project slug: {project!r}\n"
                f"Known projects: {known}"
            )
    else:
        project = resolve_project_from_cwd(cwd, projects)
        if project is None:
            raise ValueError(
                f"No project could be inferred from the current directory: {cwd}\n"
                f"Use --project to specify the project, e.g.:\n"
                f"  operator do \"{raw_input}\" --project <slug>"
            )

    # --- 2. Wide scope protection ---
    wide_scope = _has_wide_scope(raw_input) or _is_top_level_cwd(cwd)

    # --- 3. Score risk ---
    risk_score = score_risk(raw_input, project, {"projects": projects})

    # Enforce minimum normalization for wide scope
    if wide_scope and risk_score["normalization_path"] == "fast":
        risk_score = {**risk_score, "normalization_path": "normal"}

    # --- 4. Select normalizer ---
    normalizer = select_normalizer(risk_score)
    if wide_scope and normalizer == "local":
        normalizer = "codex"

    if risk_score["normalization_path"] in ("normal", "deep"):
        print(
            f"[intake] normalization: {risk_score['normalization_path']} "
            f"(risk={risk_score['risk_level']})",
            file=sys.stderr,
        )
        if risk_score.get("triggered_keywords"):
            print(
                f"[intake] triggered keywords: {', '.join(risk_score['triggered_keywords'])}",
                file=sys.stderr,
            )

    # --- 5. Normalize ---
    task = normalize_task(
        raw_input,
        project,
        cwd,
        projects,
        policies,
        risk_score=risk_score,
        agent_override=agent_override,
        normalizer_override=normalizer,
    )

    # Stamp the source context entrypoint
    task = _stamp_source_context(task, raw_input, entrypoint="do")

    # --- 6. Display ---
    display_task(task)

    # --- 7. Confirmation ---
    if dry_run:
        print("(dry-run: task not queued)")
        return task

    if not skip_confirmation and task.requires_confirmation:
        try:
            answer = input("Proceed? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nTask cancelled.")
            raise SystemExit(1)
        if answer not in ("", "y", "yes"):
            print("Task cancelled.")
            raise SystemExit(0)

    return task


def _stamp_source_context(task: StandardizedTask, raw_input: str, entrypoint: str) -> StandardizedTask:
    """Return a copy of task with source_context.entrypoint correctly set."""
    updated_ctx = {
        **task.source_context,
        "entrypoint": entrypoint,
        "raw_input": raw_input,
    }
    # StandardizedTask is frozen; use object.__setattr__ workaround is not available.
    # Reconstruct with updated source_context.
    from dataclasses import asdict
    d = asdict(task)
    d["source_context"] = updated_ctx
    return StandardizedTask(**d)
