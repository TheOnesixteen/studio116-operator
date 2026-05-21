from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.models import CommandResult


def intended_read_only_command(*, packet_path: Path) -> list[str]:
    prompt = (
        f"You are the planner agent. Read the worker packet at {packet_path} "
        "and produce a concise implementation plan. Output only the plan as plain text."
    )
    return ["claude", "-p", prompt]


def run_read_only(
    task: dict[str, Any],
    run_id: str,
    worktree_path: Path,
    packet_path: Path,
    timeout_seconds: int = 600,
) -> CommandResult:
    try:
        packet_content = packet_path.read_text(encoding="utf-8")
    except OSError as exc:
        return CommandResult(
            command="claude",
            stdout="",
            stderr=f"Unable to read worker packet {packet_path}: {exc}",
            exit_code=1,
        )
    prompt = (
        "You are the planner agent. Here is the worker packet:\n\n"
        f"{packet_content}\n\n"
        "Produce a concise implementation plan. Output only the plan as plain text."
    )
    command = ["claude", "-p", prompt]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        result = CommandResult(
            command="claude -p <prompt>",
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        result = CommandResult(
            command="claude -p <prompt>",
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=exc.stderr if isinstance(exc.stderr, str) else "Claude Code execution timed out",
            exit_code=124,
            timed_out=True,
        )
    except OSError as exc:
        return CommandResult(
            command="claude -p <prompt>",
            stdout="",
            stderr=f"Claude Code execution failed to start: {exc}",
            exit_code=127,
        )
    if result.exit_code == 0 and result.stdout:
        context_path = worktree_path / "pipeline_context.txt"
        context_path.write_text(result.stdout, encoding="utf-8")
    return result
