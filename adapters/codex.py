from __future__ import annotations

from pathlib import Path


def intended_dry_run_command(*, packet_path: Path, worktree_path: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "--cwd",
        str(worktree_path),
        "--packet",
        str(packet_path),
    ]
