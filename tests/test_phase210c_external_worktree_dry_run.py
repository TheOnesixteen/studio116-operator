import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

from app.main import main
from app.project_registry import dry_run_external_worktree


def _write_policy(*, writable: bool = True, allowed_lane: str | None = "docs_only") -> dict:
    return {
        "writable": writable,
        "allowed_write_agents": ["codex"] if writable else [],
        "allowed_lane": allowed_lane,
        "max_changed_files": 1,
        "allow_file_creation": False,
        "requires_human_approval": True,
        "deployment_allowed": False,
    }


def _project(slug: str, repo_path: Path, *, write_policy: dict | None = None) -> dict:
    project = {
        "slug": slug,
        "name": slug.title(),
        "repo_path": str(repo_path),
        "stack": ["python"],
        "domains": [],
        "services": [],
        "allowed_agents": ["codex", "claude_code"],
        "deployment_method": "manual",
        "status": "planned",
        "notes": "Test project.",
    }
    if write_policy is not None:
        project["write_policy"] = write_policy
    return project


def _write_registry(projects: dict) -> Path:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    with handle:
        yaml.safe_dump({"projects": projects}, handle, sort_keys=False)
    return Path(handle.name)


def _run_git(repo_path: Path, args: list[str]) -> None:
    subprocess.run(["git", "-C", str(repo_path), *args], check=True, capture_output=True, text=True)


def _init_git_repo(root: Path, *, dirty: bool = False) -> Path:
    repo_path = root / "repo"
    repo_path.mkdir(parents=True)
    subprocess.run(["git", "init", str(repo_path)], check=True, capture_output=True, text=True)
    (repo_path / "README.md").write_text("# Test\n", encoding="utf-8")
    _run_git(repo_path, ["add", "README.md"])
    _run_git(repo_path, ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial"])
    if dirty:
        (repo_path / "README.md").write_text("# Test\n\nDirty\n", encoding="utf-8")
    return repo_path


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class Phase210cExternalWorktreeDryRunTests(unittest.TestCase):
    def test_policy_blocked_path_stops_before_repo_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_path = Path(tmp) / "missing"
            registry_path = _write_registry({"blocked": _project("blocked", repo_path, write_policy=_write_policy(writable=False, allowed_lane=None))})

            result = dry_run_external_worktree("blocked", worker="codex", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "policy_blocked")
        self.assertFalse(result.safe)
        self.assertEqual(result.preflight.result_code, "known_non_writable")
        self.assertIn("External write preflight did not authorize this request.", result.reasons)

    def test_missing_canonical_repo_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_path = Path(tmp) / "missing"
            registry_path = _write_registry({"missingrepo": _project("missingrepo", repo_path, write_policy=_write_policy())})

            result = dry_run_external_worktree("missingrepo", worker="codex", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "canonical_repo_missing")
        self.assertFalse(result.safe)
        self.assertIn("repo_path does not exist.", result.reasons)

    def test_non_git_canonical_repo_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_path = Path(tmp) / "repo"
            repo_path.mkdir()
            registry_path = _write_registry({"nongit": _project("nongit", repo_path, write_policy=_write_policy())})

            result = dry_run_external_worktree("nongit", worker="codex", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "canonical_repo_not_git")
        self.assertFalse(result.safe)
        self.assertIn("repo_path is not a git work tree.", result.reasons)

    def test_dirty_canonical_repo_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_path = _init_git_repo(Path(tmp), dirty=True)
            registry_path = _write_registry({"dirty": _project("dirty", repo_path, write_policy=_write_policy())})

            result = dry_run_external_worktree("dirty", worker="codex", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "canonical_repo_dirty")
        self.assertFalse(result.safe)
        self.assertIn("Canonical repo has uncommitted changes.", result.reasons)

    def test_worktree_path_collision_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_path = _init_git_repo(tmp_path)
            registry_path = _write_registry({"collision": _project("collision", repo_path, write_policy=_write_policy())})
            runtime_dir = tmp_path / "runtime"
            collision_path = runtime_dir / "worktrees" / "external" / "collision" / "codex" / "docs_only"
            collision_path.mkdir(parents=True)

            with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": str(runtime_dir)}):
                result = dry_run_external_worktree("collision", worker="codex", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "worktree_path_collision")
        self.assertFalse(result.safe)
        self.assertIn("Intended worktree path already exists.", result.reasons)

    def test_canonical_repo_nested_inside_operator_repo_blocks(self):
        nested_repo = Path("tmp_phase210c_nested_repo").resolve()
        registry_path = _write_registry({"nested": _project("nested", nested_repo, write_policy=_write_policy())})

        result = dry_run_external_worktree("nested", worker="codex", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "canonical_repo_unsafe_path")
        self.assertFalse(result.safe)
        self.assertIn("External canonical repo must not be inside the Operator repo.", result.reasons)

    def test_clean_canonical_repo_with_safe_worktree_plan_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo_path = _init_git_repo(tmp_path)
            registry_path = _write_registry({"clean": _project("clean", repo_path, write_policy=_write_policy())})
            runtime_dir = tmp_path / "runtime"

            with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": str(runtime_dir)}):
                result = dry_run_external_worktree("clean", worker="codex", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "dry_run_safe")
        self.assertTrue(result.safe)
        self.assertIn("Dry-run passed; worktree creation would be safe to attempt in a later phase.", result.reasons)
        self.assertEqual(result.worktree_plan["branch_name"], "operator/external/clean/codex/docs-only")
        self.assertIn("git -C", result.worktree_plan["intended_command"])

    def test_cli_renders_safe_dry_run_without_db_init(self):
        preflight = SimpleNamespace(
            result_code="writable_lane_authorized",
            authorized=True,
            requested_project="clean",
            requested_worker="codex",
            requested_lane="docs_only",
            write_policy=_write_policy(),
        )
        result = SimpleNamespace(
            result_code="dry_run_safe",
            safe=True,
            preflight=preflight,
            project=_project("clean", Path("/tmp/clean"), write_policy=_write_policy()),
            repo_checks={
                "exists": True,
                "is_directory": True,
                "is_git_work_tree": "true",
                "git_top_level": "/tmp/clean",
                "head": "abc123",
                "status_porcelain": "",
            },
            worktree_plan={
                "worktree_path": "/tmp/runtime/worktrees/external/clean/codex/docs_only",
                "worktree_path_under_runtime_worktrees": True,
                "worktree_path_exists": False,
                "branch_name": "operator/external/clean/codex/docs-only",
                "intended_command": "git -C /tmp/clean worktree add -B operator/external/clean/codex/docs-only /tmp/runtime/worktrees/external/clean/codex/docs_only HEAD",
            },
            reasons=["Dry-run passed; worktree creation would be safe to attempt in a later phase."],
            next_actions=["No worktree was created. No worker was launched. No patch was promoted. No deployment occurred."],
        )
        with mock.patch("app.main.init_db") as init_db, mock.patch("app.main.validate_registry", return_value=SimpleNamespace(ok=True)), mock.patch(
            "app.main.dry_run_external_worktree", return_value=result
        ):
            exit_code, output, error = _run_cli(["projects", "dry-run-worktree", "operator", "--lane", "docs_only", "--worker", "codex"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        init_db.assert_not_called()
        self.assertIn("External worktree dry-run: would be safe", output)
        self.assertIn("Result: dry_run_safe", output)
        self.assertIn("no worktree was created", output)
        self.assertIn("no worker was launched", output)


if __name__ == "__main__":
    unittest.main()
