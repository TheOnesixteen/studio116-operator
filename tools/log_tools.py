from __future__ import annotations

import subprocess

from app.events import redact
from app.models import CommandResult
from app.policies import assert_phase1_allowed


def run_read_only_command(command: list[str], *, action: str, timeout: int = 10) -> CommandResult:
    assert_phase1_allowed(action)
    command_text = " ".join(command)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            command=command_text,
            stdout=redact(completed.stdout),
            stderr=redact(completed.stderr),
            exit_code=completed.returncode,
        )
    except FileNotFoundError as exc:
        return CommandResult(command=command_text, stdout="", stderr=str(exc), exit_code=127)
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=command_text,
            stdout=redact(exc.stdout if isinstance(exc.stdout, str) else ""),
            stderr=redact(exc.stderr if isinstance(exc.stderr, str) else "command timed out"),
            exit_code=124,
            timed_out=True,
        )


def tail_operator_log(lines: int, log_path) -> str:
    if not log_path.exists():
        return ""
    content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])
