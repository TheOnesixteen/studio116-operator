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
        "Execute this Operator live_codex_docs_only worker packet. "
        f"The packet is available at {packet_path} and is also provided on stdin as JSON. "
        "Modify only the target_paths listed in the packet. Create those files if needed. "
        "Do not install packages, use network-dependent work, commit, merge, push, "
        "modify hidden files, modify env files, or touch deployment/config/system files. "
        "When done, leave the changes unstaged in the worktree."
    )
    return [
        "codex",
        "exec",
        "--sandbox",
        "workspace-write",
        "--json",
        "--output-last-message",
        str(packet_path.with_name("codex_last_message.txt")),
        "-C",
        str(worktree_path),
        prompt,
    ]


def _run_codex_command(command: list[str], *, packet_path: Path, timeout_seconds: int) -> CommandResult:
    try:
        packet_stdin = packet_path.read_text(encoding="utf-8")
    except OSError as exc:
        return CommandResult(
            command=" ".join(command),
            stdout="",
            stderr=f"Unable to read worker packet {packet_path}: {exc}",
            exit_code=1,
        )
    try:
        completed = subprocess.run(
            command,
            input=packet_stdin,
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
    except OSError as exc:
        return CommandResult(
            command=" ".join(command),
            stdout="",
            stderr=f"Codex execution failed to start: {exc}",
            exit_code=127,
        )


def live_tests_only_command(*, worktree_path: Path, packet_path: Path) -> list[str]:
    prompt = (
        "Use the worker packet at "
        f"{packet_path}. Perform only the requested tests-only target path change. "
        "Modify only tests/test_*.py files. Do not install packages, use network-dependent work, "
        "commit, merge, push, modify app code, modify hidden files, modify env files, "
        "or touch deployment/config/system/runtime files."
    )
    return ["codex", "exec", "-C", str(worktree_path), prompt]


def live_policy_file_command(*, worktree_path: Path, packet_path: Path) -> list[str]:
    prompt = (
        "Use the worker packet at "
        f"{packet_path}. Perform only the requested policy-file target path change. "
        "Modify only app/policies.py. Do not install packages, use network-dependent work, "
        "commit, merge, push, modify other app files, modify tests, modify registry files, "
        "modify hidden files, modify env files, or touch deployment/config/system/runtime files."
    )
    return ["codex", "exec", "-C", str(worktree_path), prompt]


def live_model_file_command(*, worktree_path: Path, packet_path: Path) -> list[str]:
    prompt = (
        "Execute this Operator live_codex_model_file_only worker packet. "
        f"The packet is available at {packet_path} and is also provided on stdin as JSON. "
        "Modify only the target_paths listed in the packet. Create those files if needed. "
        "Do not install packages, use network-dependent work, "
        "commit, merge, push, modify files outside target_paths, "
        "modify hidden files, modify env files, or touch deployment/config/system/runtime files. "
        "When done, leave the changes unstaged in the worktree."
    )
    return [
        "codex",
        "exec",
        "--sandbox",
        "workspace-write",
        "--json",
        "--output-last-message",
        str(packet_path.with_name("codex_last_message.txt")),
        "-C",
        str(worktree_path),
        prompt,
    ]


def live_scaffold_only_command(*, worktree_path: Path, packet_path: Path) -> list[str]:
    prompt = (
        "Execute this Operator live_codex_scaffold_only worker packet. "
        f"The packet is available at {packet_path} and is also provided on stdin as JSON. "
        "Modify only the target_paths listed in the packet. Create those files if needed. "
        "Do not modify app/ai_generation.py, email sender code, hidden files, env files, secrets, "
        "deployment files, systemd files, Caddyfile, runtime config, publishing jobs, or files outside target_paths. "
        "Do not install packages, use network-dependent work, commit, merge, or push. "
        "When done, leave the changes unstaged in the worktree."
    )
    return [
        "codex",
        "exec",
        "--sandbox",
        "workspace-write",
        "--json",
        "--output-last-message",
        str(packet_path.with_name("codex_last_message.txt")),
        "-C",
        str(worktree_path),
        prompt,
    ]


def run_live_docs_only(*, worktree_path: Path, packet_path: Path, timeout_seconds: int = 600) -> CommandResult:
    command = live_docs_only_command(worktree_path=worktree_path, packet_path=packet_path)
    return _run_codex_command(command, packet_path=packet_path, timeout_seconds=timeout_seconds)


def run_live_policy_file(*, worktree_path: Path, packet_path: Path, timeout_seconds: int = 600) -> CommandResult:
    command = live_policy_file_command(worktree_path=worktree_path, packet_path=packet_path)
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


def run_live_model_file(*, worktree_path: Path, packet_path: Path, timeout_seconds: int = 600) -> CommandResult:
    command = live_model_file_command(worktree_path=worktree_path, packet_path=packet_path)
    return _run_codex_command(command, packet_path=packet_path, timeout_seconds=timeout_seconds)


def run_live_scaffold_only(*, worktree_path: Path, packet_path: Path, timeout_seconds: int = 600) -> CommandResult:
    command = live_scaffold_only_command(worktree_path=worktree_path, packet_path=packet_path)
    return _run_codex_command(command, packet_path=packet_path, timeout_seconds=timeout_seconds)


def pipeline_docs_command(*, worktree_path: Path, packet_path: Path) -> list[str]:
    prompt = (
        "Execute this Operator sequential_pipeline worker packet. "
        f"The packet is available at {packet_path} and is also provided on stdin as JSON. "
        "A planning context from the prior pipeline agent is in the packet under 'pipeline_context'. "
        "Modify only the target_paths listed in the packet. Create those files if needed. "
        "Do not install packages, use network-dependent work, commit, merge, push, "
        "modify hidden files, modify env files, or touch deployment/config/system files. "
        "When done, leave the changes unstaged in the worktree."
    )
    return [
        "codex",
        "exec",
        "--sandbox",
        "workspace-write",
        "--json",
        "--output-last-message",
        str(packet_path.with_name("codex_last_message.txt")),
        "-C",
        str(worktree_path),
        prompt,
    ]


def run_pipeline_codex(*, worktree_path: Path, packet_path: Path, timeout_seconds: int = 600) -> CommandResult:
    command = pipeline_docs_command(worktree_path=worktree_path, packet_path=packet_path)
    return _run_codex_command(command, packet_path=packet_path, timeout_seconds=timeout_seconds)


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
