from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.models import CommandResult

_DEVNULL = subprocess.DEVNULL


def intended_review_command(*, packet_path: Path) -> list[str]:
    return [
        "gemini",
        "--output-format", "text",
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
    try:
        packet_content = packet_path.read_text(encoding="utf-8")
    except OSError as exc:
        return CommandResult(
            command="gemini",
            stdout="",
            stderr=f"Unable to read worker packet {packet_path}: {exc}",
            exit_code=1,
        )
    if context_path is not None:
        try:
            context_content = context_path.read_text(encoding="utf-8")
        except OSError:
            context_content = ""
        prompt = (
            "You are the reviewer. Here is the worker packet:\n\n"
            f"{packet_content}\n\n"
            f"Here is the implementation to review:\n\n{context_content}\n\n"
            "Output only your review as plain text."
        )
    else:
        prompt = (
            "You are the planner agent. Here is the worker packet:\n\n"
            f"{packet_content}\n\n"
            "Produce a concise implementation plan. Output only the plan as plain text."
        )
    command = ["gemini", "--output-format", "text", "-p", prompt]
    try:
        completed = subprocess.run(
            command,
            stdin=_DEVNULL,
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
