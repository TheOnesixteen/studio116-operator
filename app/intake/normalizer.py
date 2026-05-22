from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.models import StandardizedTask
from app.intake.context_resolver import snapshot_blocked_paths


# Verbs that map to a delegated implementation task type
_IMPL_VERBS = {"add", "create", "implement", "build", "write", "fix", "update", "generate", "make"}
# Verbs that map to health_check / read-only
_READ_VERBS = {"check", "inspect", "show", "list", "view", "get", "read", "status", "verify", "test"}
# Verbs that map to review
_REVIEW_VERBS = {"review", "audit", "critique", "analyse", "analyze", "evaluate"}
# Verbs that map to planning
_PLAN_VERBS = {"plan", "design", "architect", "outline", "document", "spec", "draft"}

_NORMALIZATION_PROMPT_TEMPLATE = """\
You are normalizing a quick task for the Studio 116 Operator.

Project: {project_slug}
Project stack: {stack}
Current directory: {origin_directory}
Raw input: "{raw_goal}"

Produce a JSON object with exactly these fields:
- title: short task title (max 60 chars)
- goal: clear goal statement (1-2 sentences)
- steps: ordered list of concrete steps (max 5, each a string)
- target_paths: list of files likely involved (be specific, not "*")
- acceptance_criteria: list of testable outcomes (each a string)
- task_type: one of delegated | health_check | review | planning
- delegation_mode: one of dry_run | live_codex_docs_only | live_codex_tests_only | live_codex_policy_file_only | live_codex_model_file_only | live_codex_scaffold_only
- agent: one of codex | claude_code | gemini_cli | shell_ops
- write_intent: true if files will be changed, false if read-only
- confidence: 0.0-1.0 how confident you are in this interpretation
- normalization_note: empty string, or explanation if confidence < 0.7

If target_paths is ambiguous, return an empty list — do not guess file paths.
Return only valid JSON. No explanation, no markdown fences.
"""


def select_normalizer(risk_score: dict[str, Any]) -> str:
    """
    Decide which normalizer to use based on the risk score.

    Returns "local" | "codex" | "claude"

    local:  risk=low, no fuzzy/architecture signals
    codex:  default for implementation tasks, risk=low|medium
    claude: architecture keywords detected, risk=high, or goal is fuzzy
    """
    if risk_score.get("escalate_to_claude") or risk_score.get("risk_level") == "high":
        return "claude"
    if risk_score.get("normalization_path") == "fast" and not risk_score.get("is_fuzzy"):
        return "local"
    return "codex"


def _infer_task_type(goal_lower: str) -> str:
    """Infer task_type from the goal text using verb analysis."""
    words = set(goal_lower.split())
    if words & _REVIEW_VERBS:
        return "review"
    if words & _PLAN_VERBS:
        return "planning"
    if words & _READ_VERBS:
        return "health_check"
    if words & _IMPL_VERBS:
        return "delegated"
    return "delegated"


def _infer_agent(task_type: str, goal_lower: str) -> str:
    """Infer the agent from task type and goal content."""
    if task_type == "health_check":
        return "shell_ops"
    if task_type in {"review", "planning"}:
        return "claude_code"
    return "codex"


def _infer_delegation_mode(task_type: str, goal_lower: str) -> str:
    """Infer delegation mode from task type and goal keywords."""
    if task_type in {"health_check", "review", "planning"}:
        return "dry_run"
    if _has_explicit_docs_intent(goal_lower):
        return "live_codex_docs_only"
    if "test" in goal_lower:
        return "live_codex_tests_only"
    if "model" in goal_lower or "models.py" in goal_lower:
        return "live_codex_model_file_only"
    if "polic" in goal_lower or "policies.py" in goal_lower:
        return "live_codex_policy_file_only"
    if any(kw in goal_lower for kw in ("doc", "readme", "changelog", "operator.md")):
        return "live_codex_docs_only"
    return "dry_run"


def _has_explicit_docs_intent(goal_lower: str) -> bool:
    return any(
        marker in goal_lower
        for marker in (
            "docs/",
            "docs-only",
            "documentation",
            "handbook",
            "manual",
            "readme",
            "operator.md",
            ".md",
            "docs/operator-handbook/",
        )
    )


def _infer_local_target_paths(raw_goal: str, delegation_mode: str) -> list[str]:
    if delegation_mode != "live_codex_docs_only":
        return []

    paths: list[str] = []
    handbook_match = re.search(r"docs/operator-handbook/?", raw_goal, flags=re.IGNORECASE)
    for match in re.findall(r"(?<![\w./-])([A-Za-z0-9_./-]+\.md)\b", raw_goal):
        path = match.strip().lstrip("./")
        if handbook_match and "/" not in path:
            continue
        if path and path not in paths:
            paths.append(path)

    if handbook_match:
        handbook_prefix = "docs/operator-handbook/"
        for match in re.findall(r"(?m)^\s*-\s*([A-Za-z0-9_.-]+\.md)\s*$", raw_goal):
            path = handbook_prefix + match.strip()
            if path not in paths:
                paths.append(path)
        if not paths:
            paths.append(handbook_prefix + "README.md")

    return paths


def _compute_local_confidence(raw_goal: str, project: str | None) -> float:
    """Estimate confidence that local (no-AI) normalization is accurate."""
    score = 0.0
    words = raw_goal.lower().split()
    word_set = set(words)

    # Project clearly known
    if project:
        score += 0.30

    # Goal contains a specific, recognizable action verb
    if word_set & (_IMPL_VERBS | _READ_VERBS | _REVIEW_VERBS | _PLAN_VERBS):
        score += 0.25

    # Goal is reasonably specific (4+ words)
    if len(words) >= 4:
        score += 0.15

    # No vague pronouns suggesting missing context
    vague_tokens = {"thing", "stuff", "it", "this", "that", "something"}
    if not (word_set & vague_tokens):
        score += 0.15

    # Recognizable module/file reference
    if any(c in raw_goal for c in (".", "_", "/")):
        score += 0.15

    return min(score, 1.0)


def _normalize_local(
    raw_goal: str,
    project: str,
    origin_dir: str,
    projects: dict[str, Any],
    policies: dict[str, Any],
    risk_score: dict[str, Any],
    agent_override: str | None = None,
) -> StandardizedTask:
    """
    Build a StandardizedTask using deterministic heuristics only — no AI call.
    Used for Level 1 (fast) normalization when confidence is sufficiently high.
    """
    goal_lower = raw_goal.lower()
    confidence = _compute_local_confidence(raw_goal, project)

    task_type = _infer_task_type(goal_lower)
    agent = agent_override or _infer_agent(task_type, goal_lower)
    delegation_mode = _infer_delegation_mode(task_type, goal_lower)
    target_paths = _infer_local_target_paths(raw_goal, delegation_mode)

    write_intent = task_type == "delegated" and delegation_mode != "dry_run"
    read_only = not write_intent

    title = raw_goal[:60].strip()
    goal = raw_goal.strip()

    steps: list[str] = []
    acceptance_criteria: list[str] = ["Task completes without errors"]
    scope = [task_type]

    blocked_paths = snapshot_blocked_paths(project, policies)
    requires_confirmation = confidence < 0.85

    routing_reason = (
        f"Local normalization — "
        f"task_type={task_type}, confidence={confidence:.2f}, "
        f"project inferred from cwd"
    )

    return StandardizedTask(
        title=title,
        goal=goal,
        project=project,
        task_type=task_type,
        agent=agent,
        delegation_mode=delegation_mode,
        scope=scope,
        target_paths=target_paths,
        blocked_paths=blocked_paths,
        origin_directory=os.path.realpath(origin_dir),
        steps=steps,
        acceptance_criteria=acceptance_criteria,
        risk_level=risk_score.get("risk_level", "low"),
        normalization_path="fast",
        confidence=confidence,
        write_intent=write_intent,
        read_only=read_only,
        requires_confirmation=requires_confirmation,
        requires_gemini_review=risk_score.get("requires_gemini_review", False),
        source_context={
            "entrypoint": "do",
            "raw_input": raw_goal,
            "spec_path": None,
            "referenced_artifacts": [],
        },
        routing_reason=routing_reason,
        normalization_notes=risk_score.get("triggered_keywords", []),
    )


def _load_anthropic_key() -> str | None:
    """Load the Anthropic API key from ~/.anthropic_key without exposing it."""
    key_path = Path.home() / ".anthropic_key"
    try:
        key = key_path.read_text(encoding="utf-8").strip()
        return key if key else None
    except OSError:
        return None


def _call_codex_for_normalization(
    raw_goal: str,
    project: str,
    stack: list[str],
    origin_dir: str,
) -> dict[str, Any]:
    """
    Invoke the Codex CLI with a normalization prompt using the existing adapter
    pattern (exec + workspace-write sandbox + output-last-message).
    Returns a dict with normalization fields, or an error dict on failure.
    """
    prompt = _NORMALIZATION_PROMPT_TEMPLATE.format(
        project_slug=project,
        stack=", ".join(stack) if stack else "unknown",
        origin_directory=origin_dir,
        raw_goal=raw_goal,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = str(Path(tmpdir) / "codex_normalization.txt")
        command = [
            "codex", "exec",
            "--sandbox", "workspace-write",
            "--json",
            "--output-last-message", output_file,
            "-C", tmpdir,
            prompt,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except FileNotFoundError:
            return {"error": "Codex CLI not found in PATH", "confidence": 0.0}
        except subprocess.TimeoutExpired:
            return {"error": "Codex normalization timed out after 30s", "confidence": 0.0}

        content = ""
        output_path = Path(output_file)
        if output_path.exists():
            content = output_path.read_text(encoding="utf-8").strip()
        if not content:
            content = result.stdout.strip()

        if not content:
            return {
                "error": "Codex produced no output",
                "confidence": 0.0,
                "exit_code": result.returncode,
            }

        # Try direct JSON parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try to extract a JSON object from the response
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return {
            "error": "Could not parse Codex response as JSON",
            "confidence": 0.0,
            "raw_excerpt": content[:300],
        }


def _call_claude_for_normalization(
    raw_goal: str,
    project: str,
    stack: list[str],
    origin_dir: str,
) -> dict[str, Any]:
    """
    Call the Anthropic API via HTTP to normalize a task using Claude.
    Loads the API key from ~/.anthropic_key without exposing it.
    Returns a dict with normalization fields, or an error dict on failure.
    """
    import requests  # already installed; no new dependency

    api_key = _load_anthropic_key()
    if not api_key:
        return {
            "error": "~/.anthropic_key not found or empty; cannot call Claude",
            "confidence": 0.0,
        }

    prompt = _NORMALIZATION_PROMPT_TEMPLATE.format(
        project_slug=project,
        stack=", ".join(stack) if stack else "unknown",
        origin_directory=origin_dir,
        raw_goal=raw_goal,
    )

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
    except Exception as exc:
        return {"error": f"Claude API request failed: {exc}", "confidence": 0.0}

    if response.status_code != 200:
        return {
            "error": f"Claude API returned HTTP {response.status_code}",
            "confidence": 0.0,
        }

    try:
        data = response.json()
        content = data["content"][0]["text"].strip()
    except (KeyError, IndexError, ValueError) as exc:
        return {"error": f"Unexpected Claude API response shape: {exc}", "confidence": 0.0}

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {
        "error": "Could not parse Claude response as JSON",
        "confidence": 0.0,
        "raw_excerpt": content[:300],
    }


def _build_from_ai_result(
    ai_result: dict[str, Any],
    raw_goal: str,
    project: str,
    origin_dir: str,
    projects: dict[str, Any],
    policies: dict[str, Any],
    risk_score: dict[str, Any],
    normalizer_name: str,
    agent_override: str | None = None,
) -> StandardizedTask:
    """
    Convert an AI normalizer result dict into a StandardizedTask.
    Falls back to safe defaults for any missing or invalid fields.
    """
    error = ai_result.get("error")
    notes: list[str] = []
    if error:
        notes.append(f"Normalization error: {error}")

    title = str(ai_result.get("title", raw_goal[:60])).strip()[:60]
    goal = str(ai_result.get("goal", raw_goal)).strip() or raw_goal

    raw_steps = ai_result.get("steps", [])
    steps = [str(s) for s in raw_steps if s] if isinstance(raw_steps, list) else []

    raw_criteria = ai_result.get("acceptance_criteria", [])
    acceptance_criteria = (
        [str(c) for c in raw_criteria if c] if isinstance(raw_criteria, list)
        else ["Task completes without errors"]
    ) or ["Task completes without errors"]

    raw_paths = ai_result.get("target_paths", [])
    target_paths = [str(p) for p in raw_paths if p] if isinstance(raw_paths, list) else []

    task_type_raw = str(ai_result.get("task_type", "delegated")).strip()
    valid_task_types = {"delegated", "health_check", "review", "planning"}
    task_type = task_type_raw if task_type_raw in valid_task_types else "delegated"

    delegation_mode_raw = str(ai_result.get("delegation_mode", "dry_run")).strip()
    valid_modes = {
        "dry_run", "live_codex_docs_only", "live_codex_tests_only",
        "live_codex_policy_file_only", "live_codex_model_file_only", "live_codex_scaffold_only",
    }
    delegation_mode = delegation_mode_raw if delegation_mode_raw in valid_modes else "dry_run"

    valid_agents = {"codex", "claude_code", "gemini_cli", "shell_ops"}
    agent_raw = str(ai_result.get("agent", "codex")).strip()
    agent = agent_override or (agent_raw if agent_raw in valid_agents else "codex")

    write_intent = bool(ai_result.get("write_intent", False))
    read_only = not write_intent

    try:
        confidence = float(ai_result.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.5

    normalization_note = str(ai_result.get("normalization_note", "")).strip()
    if normalization_note:
        notes.append(normalization_note)
    notes.extend(risk_score.get("triggered_keywords", []))

    blocked_paths = snapshot_blocked_paths(project, policies)

    routing_reason = (
        f"{normalizer_name} normalization — "
        f"risk={risk_score.get('risk_level', 'unknown')}, "
        f"confidence={confidence:.2f}"
    )
    if error:
        routing_reason += f" (fallback: {error[:60]})"

    normalization_path = risk_score.get("normalization_path", "normal")
    if normalizer_name == "codex":
        normalization_path = "normal"
    elif normalizer_name == "claude":
        normalization_path = "deep"

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
        origin_directory=os.path.realpath(origin_dir),
        steps=steps,
        acceptance_criteria=acceptance_criteria,
        risk_level=risk_score.get("risk_level", "low"),
        normalization_path=normalization_path,
        confidence=confidence,
        write_intent=write_intent,
        read_only=read_only,
        requires_confirmation=True,
        requires_gemini_review=risk_score.get("requires_gemini_review", False),
        source_context={
            "entrypoint": "do",
            "raw_input": raw_goal,
            "spec_path": None,
            "referenced_artifacts": [],
        },
        routing_reason=routing_reason,
        normalization_notes=notes,
    )


def normalize_task(
    raw_goal: str,
    project: str,
    origin_dir: str,
    projects: dict[str, Any],
    policies: dict[str, Any],
    *,
    risk_score: dict[str, Any],
    agent_override: str | None = None,
    normalizer_override: str | None = None,
) -> StandardizedTask:
    """
    Normalize a raw goal string into a StandardizedTask using the appropriate
    normalization level (local / codex / claude) based on risk and confidence.

    Levels:
      fast / local  — deterministic, no AI, < 1 second
      normal / codex — Codex CLI, 5-15 seconds
      deep / claude  — Claude API, 15-45 seconds + optional Gemini stub
    """
    normalizer = normalizer_override or select_normalizer(risk_score)

    # Load project stack for AI normalizers
    project_data = projects.get(project, {})
    stack = project_data.get("stack", [])

    if normalizer == "local":
        task = _normalize_local(
            raw_goal, project, origin_dir, projects, policies, risk_score,
            agent_override=agent_override,
        )
        return task

    if normalizer == "codex":
        ai_result = _call_codex_for_normalization(raw_goal, project, stack, origin_dir)
        return _build_from_ai_result(
            ai_result, raw_goal, project, origin_dir, projects, policies,
            risk_score, "codex", agent_override=agent_override,
        )

    # claude (deep normalization)
    ai_result = _call_claude_for_normalization(raw_goal, project, stack, origin_dir)
    task = _build_from_ai_result(
        ai_result, raw_goal, project, origin_dir, projects, policies,
        risk_score, "claude", agent_override=agent_override,
    )

    # Gemini review stub
    if task.requires_gemini_review:
        print("Gemini review: [not yet implemented]")

    return task


def _one_line(text: str, max_len: int = 80) -> str:
    """Return first line of text, truncated to max_len chars."""
    first = text.splitlines()[0].strip() if text else ""
    if len(first) > max_len:
        first = first[: max_len - 3] + "..."
    return first


def display_task(task: StandardizedTask) -> None:
    """
    Print the interpreted task in the standard Operator display format.
    Does not print the confirmation prompt — the caller handles that.
    """
    files_display = ", ".join(task.target_paths) if task.target_paths else "(none specified)"
    if task.read_only and not task.target_paths:
        files_display = "(read-only, no files changed)"

    print()
    print("Interpreted task:")
    print(f"  Project:  {task.project}")
    print(f"  Goal:     {_one_line(task.goal)}")
    print(f"  Worker:   {task.agent}")
    print(f"  Files:    {files_display}")
    print(f"  Risk:     {task.risk_level}")
    if task.routing_reason:
        print(f"  Why:      {_one_line(task.routing_reason, 90)}")
    if task.normalization_notes:
        print(f"  Notes:    {', '.join(str(n) for n in task.normalization_notes)}")
    print()

    if task.write_intent:
        print("No files will be changed until you approve.")
    else:
        print("This task is read-only. No files will be changed.")
