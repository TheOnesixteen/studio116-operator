"""
Preview worker — called by web/app.py as a subprocess.
Reads JSON from stdin, outputs JSON to stdout.
Runs from PROJECT_ROOT so that `app.*` imports resolve correctly.
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

# Fix sys.path: Python adds the script's directory (web/) to sys.path[0],
# which shadows the operator `app/` package with Flask's app.py.
# Reorder so PROJECT_ROOT comes first.
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
sys.path = [_project_root] + [p for p in sys.path if os.path.realpath(p) != os.path.realpath(_script_dir)]


def main() -> None:
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as exc:
        _out({"ok": False, "error": f"bad JSON input: {exc}"})
        return

    task_text: str = req.get("task", "").strip()
    project_slug: str = (req.get("project") or "").strip()
    mode: str = (req.get("mode") or "auto").strip()
    project_root: str = req.get("project_root", ".")

    if not task_text:
        _out({"ok": False, "error": "missing 'task' field"})
        return

    try:
        from app.project_registry import load_projects
        from app.policies import load_policy_registry
        from app.intake.risk_scorer import score_risk
        from app.intake.normalizer import normalize_task, select_normalizer
        from app.intake.context_resolver import resolve_project_from_cwd

        projects_data = load_projects()
        policies = load_policy_registry()

        if project_slug in ("", "auto", "scratchpad"):
            project = resolve_project_from_cwd(project_root, projects_data) or "operator"
        else:
            if project_slug not in projects_data:
                _out({"ok": False, "error": f"Unknown project: {project_slug}"})
                return
            project = project_slug

        risk_score = score_risk(task_text, project, {"projects": projects_data})

        if mode == "fast":
            effective_normalizer = "local"
        elif mode == "normal":
            effective_normalizer = "codex"
        elif mode == "deep":
            effective_normalizer = "claude"
        else:
            effective_normalizer = select_normalizer(risk_score)

        # Always use local normalizer for preview (no AI cost, instant)
        _null = io.StringIO()
        _real_stdout, _real_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = _null
        try:
            task_obj = normalize_task(
                task_text,
                project,
                project_root,
                projects_data,
                policies,
                risk_score=risk_score,
                normalizer_override="local",
            )
        finally:
            sys.stdout, sys.stderr = _real_stdout, _real_stderr

        project_data = projects_data.get(project, {})
        repo_path = project_data.get("repo_path", "")
        brain_available = False
        brain_file = None
        if repo_path:
            for name in ("CLAUDE.md", "AGENTS.md", "OPERATOR.md", "README.md"):
                if (Path(repo_path) / name).exists():
                    brain_available = True
                    brain_file = name
                    break

        # When the user explicitly picks "normal" or "deep", the local normalizer's
        # dry_run fallback undersells what will actually run. Override to
        # sequential_pipeline for delegated and planning tasks so the preview is honest.
        delegation_mode = task_obj.delegation_mode
        if (
            mode in ("normal", "deep")
            and delegation_mode == "dry_run"
            and task_obj.task_type in ("delegated", "planning")
        ):
            delegation_mode = "sequential_pipeline"

        pipeline_map = {
            "live_codex_docs_only":        "agent1 → Codex",
            "live_codex_scaffold_only":    "agent1 → Codex",
            "live_codex_tests_only":       "agent1 → Codex",
            "live_codex_model_file_only":  "agent1 → Codex",
            "live_codex_policy_file_only": "agent1 → Codex",
            "sequential_pipeline":         "Claude → Codex",
            "dry_run":                     "Dry Run",
        }

        _out({
            "ok": True,
            "preview": {
                "project": task_obj.project,
                "pipeline": pipeline_map.get(delegation_mode, delegation_mode),
                "pipeline_raw": delegation_mode,
                "risk_level": task_obj.risk_level,
                "agent1": task_obj.agent,
                "target_paths": task_obj.target_paths,
                "brain_available": brain_available,
                "brain_file": brain_file,
                "normalizer": effective_normalizer,
                "normalization_path": risk_score.get("normalization_path", "fast"),
                "triggered_keywords": risk_score.get("triggered_keywords", []),
            },
        })

    except Exception as exc:
        _out({"ok": False, "error": str(exc)})


def _out(data: dict) -> None:
    sys.stdout.write(json.dumps(data) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
