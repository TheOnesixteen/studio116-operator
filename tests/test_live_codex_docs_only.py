import json
import os
import unittest
from pathlib import Path
from unittest import mock

from app.db import init_db
from app.models import CommandResult
from app.router import create_live_codex_docs_only_task
from app.scheduler import run_next
from app.task_engine import approve_task, reject_task, show_task


def _runtime(name: str) -> tuple[str, str]:
    runtime_dir = f"/tmp/{name}"
    db_path = f"{runtime_dir}/operator.db"
    if os.path.exists(db_path):
        os.unlink(db_path)
    return runtime_dir, db_path


def _success_mocks():
    return (
        mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)),
        mock.patch("app.task_engine.run_live_docs_only", return_value=CommandResult("codex exec", "ok", "", 0)),
        mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", "diff --git a/README.md b/README.md\n", "", 0)),
        mock.patch("app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)),
        mock.patch("app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)),
    )


class LiveCodexDocsOnlyTests(unittest.TestCase):
    def test_live_codex_success_stops_in_review_and_writes_artifacts(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-success")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            patches = _success_mocks()
            preflight_seen_before_launch = {"seen": False}

            def _codex_success(*, worktree_path, packet_path, timeout_seconds):
                preflight_seen_before_launch["seen"] = (packet_path.parent / "preflight_result.json").exists()
                return CommandResult("codex exec", "ok", "", 0)

            with patches[0], mock.patch("app.task_engine.run_live_docs_only", side_effect=_codex_success) as codex_run, patches[2], patches[3], patches[4]:
                task_id = create_live_codex_docs_only_task(
                    project="operator",
                    title="README live docs task",
                    goal="Make a docs-only README.md change",
                )
                result = run_next(task_id)
            task_view = show_task(task_id)

        artifact_types = {artifact["artifact_type"] for artifact in task_view["artifacts"]}
        run = task_view["runs"][0]
        self.assertTrue(result["task_succeeded"])
        self.assertTrue(result["stop_in_review"])
        self.assertEqual(task_view["task"]["status"], "review")
        self.assertEqual(run["status"], "review")
        self.assertIn("preflight_result", artifact_types)
        self.assertIn("worker_packet", artifact_types)
        self.assertIn("worker_result", artifact_types)
        self.assertIn("git_diff", artifact_types)
        self.assertIn("changed_files", artifact_types)
        self.assertIn("review_summary", artifact_types)
        self.assertIn("/worktrees/", run["worktree_path"])
        codex_run.assert_called_once()
        self.assertTrue(preflight_seen_before_launch["seen"])

    def test_preflight_artifact_written_before_codex_launch_and_blocks_bad_project(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-preflight")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_live_docs_only"
            ) as codex_run:
                task_id = create_live_codex_docs_only_task(
                    project="vps",
                    title="Bad live docs task",
                    goal="Make a docs-only README.md change",
                )
                result = run_next(task_id)
            task_view = show_task(task_id)
            preflight = next(artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == "preflight_result")
            preflight_data = json.loads(Path(preflight["path"]).read_text(encoding="utf-8"))

        self.assertFalse(result["task_succeeded"])
        self.assertEqual(result["overall_status"], "failed")
        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertFalse(preflight_data["passed"])
        self.assertTrue(any(check["name"] == "project_is_operator" and not check["passed"] for check in preflight_data["checks"]))
        codex_run.assert_not_called()

    def test_timeout_fails_and_preserves_worktree_record(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-timeout")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_live_docs_only",
                return_value=CommandResult("codex exec", "", "timeout", 124, timed_out=True),
            ):
                task_id = create_live_codex_docs_only_task(
                    project="operator",
                    title="Timeout docs task",
                    goal="Make a docs-only README.md change",
                )
                result = run_next(task_id)
            task_view = show_task(task_id)

        self.assertFalse(result["task_succeeded"])
        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertIn("/worktrees/", task_view["runs"][0]["worktree_path"])
        artifact_types = {artifact["artifact_type"] for artifact in task_view["artifacts"]}
        self.assertIn("preflight_result", artifact_types)
        self.assertIn("worker_result", artifact_types)

    def test_changed_files_validation_enforces_readme_only_post_run(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-changed-files")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_live_docs_only", return_value=CommandResult("codex exec", "ok", "", 0)
            ), mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", "diff", "", 0)), mock.patch(
                "app.task_engine.git_changed_files",
                return_value=CommandResult("git diff --name-only", "README.md\napp/main.py\n", "", 0),
            ), mock.patch(
                "app.task_engine.git_head",
                return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0),
            ):
                task_id = create_live_codex_docs_only_task(
                    project="operator",
                    title="Bad changed files task",
                    goal="Make a docs-only README.md change",
                )
                result = run_next(task_id)
            task_view = show_task(task_id)
            changed = next(artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == "changed_files")
            changed_data = json.loads(Path(changed["path"]).read_text(encoding="utf-8"))

        self.assertFalse(result["task_succeeded"])
        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertFalse(changed_data["passed"])
        self.assertTrue(any(check["name"] == "changed_files_are_readme_only" and not check["passed"] for check in changed_data["checks"]))

    def test_approve_and_reject_only_from_review(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-approve")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            patches = _success_mocks()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                task_id = create_live_codex_docs_only_task(
                    project="operator",
                    title="Approve docs task",
                    goal="Make a docs-only README.md change",
                )
                run_next(task_id)
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", "diff --git a/README.md b/README.md\n", "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_reverse_diff", return_value=CommandResult("git diff -R", "diff --git a/README.md b/README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_check", return_value=CommandResult("git apply --check", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_patch", return_value=CommandResult("git apply", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                approved = approve_task(task_id)
            with self.assertRaises(ValueError):
                reject_task(task_id)

        self.assertEqual(approved["status"], "done")
        self.assertTrue(approved["promoted"])
        self.assertTrue(approved["worktree_preserved"])

        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-reject")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            patches = _success_mocks()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                task_id = create_live_codex_docs_only_task(
                    project="operator",
                    title="Reject docs task",
                    goal="Make a docs-only README.md change",
                )
                run_next(task_id)
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", "diff --git a/README.md b/README.md\n", "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_restore_path", return_value=CommandResult("git restore -- README.md", "", "", 0)
            ):
                rejected = reject_task(task_id)

        self.assertEqual(rejected["status"], "canceled")
        self.assertTrue(rejected["discarded"])
        self.assertTrue(rejected["worktree_preserved"])


if __name__ == "__main__":
    unittest.main()
