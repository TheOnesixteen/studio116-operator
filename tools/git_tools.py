from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.config import get_settings
from app.models import CommandResult
from app.policies import assert_phase1_allowed


def slugify(value: str, *, max_length: int = 40) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return (slug or "task")[:max_length].strip("-") or "task"


def delegated_branch_name(*, task_id: str, worker: str, title: str) -> str:
    short_id = task_id.split("-")[0]
    return f"operator/{short_id}/{worker}/{slugify(title)}"


def delegated_worktree_path(*, task_id: str, worker: str) -> Path:
    return get_settings().worktrees_dir / task_id / worker


def create_worktree(*, repo_path: Path, worktree_path: Path, branch_name: str) -> CommandResult:
    assert_phase1_allowed("create_worktrees")
    assert_phase1_allowed("create_branches")
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    command = ["git", "-C", str(repo_path), "worktree", "add", "-B", branch_name, str(worktree_path), "HEAD"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    return CommandResult(
        command=" ".join(command),
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
    )


def git_diff(*, worktree_path: Path) -> CommandResult:
    command = ["git", "-C", str(worktree_path), "diff", "--no-ext-diff"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    return CommandResult(
        command=" ".join(command),
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
    )


def git_changed_files(*, worktree_path: Path) -> CommandResult:
    command = ["git", "-C", str(worktree_path), "diff", "--name-only"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    return CommandResult(
        command=" ".join(command),
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
    )


def git_head(*, worktree_path: Path) -> CommandResult:
    command = ["git", "-C", str(worktree_path), "rev-parse", "HEAD"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    return CommandResult(
        command=" ".join(command),
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
    )


def git_reverse_diff(*, worktree_path: Path) -> CommandResult:
    command = ["git", "-C", str(worktree_path), "diff", "--no-ext-diff", "-R"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    return CommandResult(
        command=" ".join(command),
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
    )


def git_apply_check(*, repo_path: Path, patch_path: Path) -> CommandResult:
    command = ["git", "-C", str(repo_path), "apply", "--check", str(patch_path)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    return CommandResult(
        command=" ".join(command),
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
    )


def git_apply_patch(*, repo_path: Path, patch_path: Path) -> CommandResult:
    command = ["git", "-C", str(repo_path), "apply", str(patch_path)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    return CommandResult(
        command=" ".join(command),
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
    )


def git_restore_path(*, worktree_path: Path, target_path: str) -> CommandResult:
    command = ["git", "-C", str(worktree_path), "restore", "--", target_path]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    return CommandResult(
        command=" ".join(command),
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
    )
