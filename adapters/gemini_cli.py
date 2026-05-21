from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.models import CommandResult


def intended_review_command(*, packet_path: Path) -> list[str]:
    return [
        "gemini",
        "-p",
        f"Review this Operator worker packet for risks, gaps, ambiguity, and recommendations. "
        f"Do not modify files. Do not execute commands. Packet path: {packet_path}",
    ]


def run_review(
    task: dict[str, Any],
    run_id: str,
    worktree_path: Path,
    packet_path: Path,
    context_path: Path | None = None,
    timeout_seconds: int = 600,
) -> CommandResult:
    if context_path is not None:
        prompt = (
            f"You are the reviewer. Read the worker packet at {packet_path} "
            f"and review the implementation at {context_path}. "
            "Output only your review as plain text."
        )
    else:
        prompt = (
            f"You are the reviewer. Read the worker packet at {packet_path} "
            "and produce a concise implementation plan. Output only the plan as plain text."
        )
    command = ["gemini", "-p", prompt]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        result = CommandResult(
            command=" ".join(command),
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        result = CommandResult(
            command=" ".join(command),
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=exc.stderr if isinstance(exc.stderr, str) else "Gemini execution timed out",
            exit_code=124,
            timed_out=True,
        )
    except OSError as exc:
        return CommandResult(
            command=" ".join(command),
            stdout="",
            stderr=f"Gemini execution failed to start: {exc}",
            exit_code=127,
        )
    if result.exit_code == 0 and result.stdout:
        context_out = worktree_path / "pipeline_context.txt"
        context_out.write_text(result.stdout, encoding="utf-8")
    return result
