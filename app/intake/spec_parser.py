from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from app.models import StandardizedTask
from app.intake.context_resolver import snapshot_blocked_paths


class SpecParseError(ValueError):
    """Raised when a spec file is missing required sections or is malformed."""


def _parse_markdown_sections(text: str) -> dict[str, str]:
    """
    Parse a markdown document into a dict of section_name -> section_body.
    H1 is stored under the key "__title__".
    H2 sections are stored under their lowercased heading text.
    """
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        if current_key is not None:
            sections[current_key] = "\n".join(current_lines).strip()

    for line in text.splitlines():
        h1 = re.match(r"^#\s+(.+)$", line)
        h2 = re.match(r"^##\s+(.+)$", line)
        if h1:
            _flush()
            current_lines = []
            current_key = "__title__"
            current_lines.append(h1.group(1).strip())
        elif h2:
            _flush()
            current_lines = []
            current_key = h2.group(1).strip().lower()
        else:
            if current_key is not None:
                current_lines.append(line)

    _flush()
    return sections


def _parse_list_section(body: str) -> list[str]:
    """
    Extract list items from a section body. Handles both:
    - Bullet lists:  "- item" or "* item"
    - Numbered lists: "1. item", "2. item"
    """
    items: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if re.match(r"^[-*]\s+", stripped):
            items.append(re.sub(r"^[-*]\s+", "", stripped).strip())
        elif re.match(r"^\d+\.\s+", stripped):
            items.append(re.sub(r"^\d+\.\s+", "", stripped).strip())
    return [item for item in items if item]


def _first_nonempty_line(body: str) -> str:
    """Return the first non-empty, non-comment line from a section body."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def parse_spec(spec_path: str) -> StandardizedTask:
    """
    Read a markdown spec file in the RedLetters format and build a StandardizedTask.

    Required sections: # Title, ## Goal, ## Project
    All other sections are optional and fall back to safe defaults.

    Raises SpecParseError with a clear message if required sections are missing.
    Sets source_context.entrypoint = "ingest".
    Snapshots blocked_paths from policies.yaml at compile time.
    """
    from app.policies import load_policy_registry

    path = Path(spec_path).resolve()
    if not path.exists():
        raise SpecParseError(f"Spec file not found: {spec_path}")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecParseError(f"Cannot read spec file: {exc}") from exc

    sections = _parse_markdown_sections(text)

    # --- Validate required sections ---
    missing: list[str] = []
    title_body = sections.get("__title__", "").strip()
    if not title_body:
        missing.append("# Title (H1 heading)")

    goal_body = sections.get("goal", "").strip()
    if not goal_body:
        missing.append("## Goal")

    project_body = sections.get("project", "").strip()
    if not project_body:
        missing.append("## Project")

    if missing:
        raise SpecParseError(
            f"Spec file is missing required sections: {', '.join(missing)}\n"
            f"File: {spec_path}"
        )

    # --- Extract required fields ---
    title = title_body[:60].strip()
    goal = goal_body.strip()
    project = _first_nonempty_line(project_body).lower().strip()
    if not project:
        raise SpecParseError(
            f"## Project section is present but empty in: {spec_path}"
        )

    # --- Extract optional fields with safe defaults ---
    agent_raw = _first_nonempty_line(sections.get("agent", "")).lower()
    valid_agents = {"codex", "claude_code", "gemini_cli", "shell_ops"}
    agent = agent_raw if agent_raw in valid_agents else "codex"

    delegation_mode_raw = _first_nonempty_line(sections.get("delegation mode", "")).lower()
    valid_modes = {
        "dry_run", "live_codex_docs_only", "live_codex_tests_only",
        "live_codex_policy_file_only", "live_codex_model_file_only", "live_codex_scaffold_only",
    }
    delegation_mode = delegation_mode_raw if delegation_mode_raw in valid_modes else "dry_run"

    target_paths = _parse_list_section(sections.get("target files", ""))

    steps = _parse_list_section(sections.get("steps", ""))

    acceptance_criteria = _parse_list_section(sections.get("acceptance criteria", ""))
    if not acceptance_criteria:
        acceptance_criteria = ["Task completes without errors"]

    risk_level_raw = _first_nonempty_line(sections.get("risk level", "")).lower()
    valid_risk = {"low", "medium", "high"}
    risk_level = risk_level_raw if risk_level_raw in valid_risk else "low"

    notes_body = sections.get("notes", "").strip()

    task_type_raw = _first_nonempty_line(sections.get("task type", "")).lower()
    valid_task_types = {"delegated", "health_check", "review", "planning"}
    if task_type_raw in valid_task_types:
        task_type = task_type_raw
    elif agent in {"codex", "claude_code"}:
        task_type = "delegated"
    else:
        task_type = "health_check"

    write_intent = bool(target_paths) and delegation_mode != "dry_run"
    read_only = not write_intent
    normalization_path = "deep" if risk_level == "high" else ("normal" if risk_level == "medium" else "fast")

    # Snapshot blocked paths from policies at compile time
    try:
        policies = load_policy_registry()
    except Exception:
        policies = {}

    blocked_paths = snapshot_blocked_paths(project, policies)
    origin_directory = os.path.realpath(os.getcwd())

    source_context: dict[str, Any] = {
        "entrypoint": "ingest",
        "raw_input": str(spec_path),
        "spec_path": str(path),
        "referenced_artifacts": [],
    }
    if notes_body:
        source_context["notes"] = notes_body

    return StandardizedTask(
        title=title,
        goal=goal,
        project=project,
        task_type=task_type,
        agent=agent,
        delegation_mode=delegation_mode,
        scope=[task_type],
        target_paths=target_paths,
        blocked_paths=blocked_paths,
        origin_directory=origin_directory,
        steps=steps,
        acceptance_criteria=acceptance_criteria,
        risk_level=risk_level,
        normalization_path=normalization_path,
        confidence=0.95,
        write_intent=write_intent,
        read_only=read_only,
        requires_confirmation=True,
        requires_gemini_review=risk_level == "high",
        source_context=source_context,
        routing_reason=f"Spec parsed from {path.name}",
        normalization_notes=[],
    )
