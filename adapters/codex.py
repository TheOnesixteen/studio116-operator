from __future__ import annotations

from pathlib import Path
import subprocess

from app.models import CommandResult


def intended_dry_run_command(*, packet_path: Path, worktree_path: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "-C",
        str(worktree_path),
        "--packet",
        str(packet_path),
    ]


def live_docs_only_command(*, worktree_path: Path, packet_path: Path) -> list[str]:
    prompt = (
        "Use the worker packet at "
        f"{packet_path}. Perform only the requested docs-only target path change. "
        "Do not install packages, use network-dependent work, commit, merge, push, "
        "modify hidden files, modify env files, or touch deployment/config/system files."
    )
    return ["codex", "exec", "-C", str(worktree_path), prompt]


def live_tests_only_command(*, worktree_path: Path, packet_path: Path) -> list[str]:
    prompt = (
        "Use the worker packet at "
        f"{packet_path}. Perform only the requested tests-only target path change. "
        "Modify only tests/test_*.py files. Do not install packages, use network-dependent work, "
        "commit, merge, push, modify app code, modify hidden files, modify env files, "
        "or touch deployment/config/system/runtime files."
    )
    return ["codex", "exec", "-C", str(worktree_path), prompt]


def run_live_docs_only(*, worktree_path: Path, packet_path: Path, timeout_seconds: int = 600) -> CommandResult:
    command = live_docs_only_command(worktree_path=worktree_path, packet_path=packet_path)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        return CommandResult(
            command=" ".join(command),
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=" ".join(command),
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=exc.stderr if isinstance(exc.stderr, str) else "Codex execution timed out",
            exit_code=124,
            timed_out=True,
        )


def run_live_tests_only(*, worktree_path: Path, packet_path: Path, timeout_seconds: int = 600) -> CommandResult:
    command = live_tests_only_command(worktree_path=worktree_path, packet_path=packet_path)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        return CommandResult(
            command=" ".join(command),
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=" ".join(command),
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=exc.stderr if isinstance(exc.stderr, str) else "Codex execution timed out",
            exit_code=124,
            timed_out=True,
        )
