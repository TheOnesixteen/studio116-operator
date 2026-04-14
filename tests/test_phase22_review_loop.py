import json
import os
import unittest
from pathlib import Path
from unittest import mock

from app.db import init_db, transaction
from app.models import CommandResult
from app.router import create_live_codex_docs_only_task
from app.scheduler import run_next
from app.task_engine import approve_task, reject_task, show_task


README_DIFF = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n"
README_ROLLBACK_DIFF = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-new\n+old\n"


def _runtime(name: str) -> tuple[str, str]:
    runtime_dir = f"/tmp/{name}"
    db_path = f"{runtime_dir}/operator.db"
    if os.path.exists(db_path):
        os.unlink(db_path)
    return runtime_dir, db_path


def _prepare_review_task(title: str = "README review loop") -> str:
    with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
        "app.task_engine.run_live_docs_only", return_value=CommandResult("codex exec", "ok", "", 0)
    ), mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
        "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
    ), mock.patch(
        "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
    ):
        task_id = create_live_codex_docs_only_task(
            project="operator",
            title=title,
            goal="Make a docs-only README.md change",
        )
        run_next(task_id)
    return task_id


def _artifact_data(task_view: dict, artifact_type: str) -> dict:
    artifact = next(artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == artifact_type)
    return json.loads(Path(artifact["path"]).read_text(encoding="utf-8"))


def _artifact_text(task_view: dict, artifact_type: str) -> str:
    artifact = next(artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == artifact_type)
    return Path(artifact["path"]).read_text(encoding="utf-8")


class Phase22ReviewLoopTests(unittest.TestCase):
    def test_approve_promotes_readme_diff_to_canonical_without_commit_merge_or_push(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase22-approve-promote")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task()
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_reverse_diff", return_value=CommandResult("git diff -R", README_ROLLBACK_DIFF, "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_check", return_value=CommandResult("git apply --check", "", "", 0)
            ) as apply_check, mock.patch(
                "app.task_engine.git_apply_patch", return_value=CommandResult("git apply", "", "", 0)
            ) as apply_patch, mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                approved = approve_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(approved["status"], "done")
        self.assertTrue(approved["promoted"])
        self.assertEqual(task_view["task"]["status"], "done")
        apply_check.assert_called_once()
        apply_patch.assert_called_once()
        commands = "\n".join(execution["command"] or "" for execution in task_view["worker_executions"])
        self.assertNotIn("git commit", commands)
        self.assertNotIn("git merge", commands)
        self.assertNotIn("git push", commands)
        summary = _artifact_data(task_view, "promotion_summary")
        self.assertFalse(summary["commit_created"])
        self.assertFalse(summary["merged"])
        self.assertFalse(summary["pushed"])

    def test_approve_requires_review_status(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase22-approve-status")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = create_live_codex_docs_only_task(
                project="operator",
                title="Queued docs task",
                goal="Make a docs-only README.md change",
            )
            with self.assertRaises(ValueError):
                approve_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(task_view["task"]["status"], "queued")

    def test_approve_blocks_when_patch_no_longer_applies_cleanly(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase22-stale-base")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task()
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_reverse_diff", return_value=CommandResult("git diff -R", README_ROLLBACK_DIFF, "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_check", return_value=CommandResult("git apply --check", "", "patch failed", 1)
            ), mock.patch(
                "app.task_engine.git_apply_patch"
            ) as apply_patch:
                with self.assertRaises(RuntimeError):
                    approve_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(task_view["task"]["status"], "review")
        apply_patch.assert_not_called()
        preflight = _artifact_data(task_view, "promotion_preflight")
        self.assertFalse(preflight["passed"])
        self.assertTrue(any(check["name"] == "canonical_git_apply_check" and not check["passed"] for check in preflight["checks"]))

    def test_approve_blocks_non_readme_changed_files(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase22-non-readme")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task()
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files",
                return_value=CommandResult("git diff --name-only", "README.md\napp/main.py\n", "", 0),
            ), mock.patch("app.task_engine.git_apply_check") as apply_check:
                with self.assertRaises(RuntimeError):
                    approve_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(task_view["task"]["status"], "review")
        apply_check.assert_not_called()
        preflight = _artifact_data(task_view, "promotion_preflight")
        self.assertFalse(preflight["passed"])
        self.assertTrue(any(check["name"] == "changed_files_are_policy_allowed" and not check["passed"] for check in preflight["checks"]))

    def test_approve_writes_promotion_summary_and_rollback_patch_artifacts(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase22-approve-artifacts")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task()
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_reverse_diff", return_value=CommandResult("git diff -R", README_ROLLBACK_DIFF, "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_check", return_value=CommandResult("git apply --check", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_patch", return_value=CommandResult("git apply", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                approve_task(task_id)
            task_view = show_task(task_id)

        artifact_types = {artifact["artifact_type"] for artifact in task_view["artifacts"]}
        self.assertIn("promotion_preflight", artifact_types)
        self.assertIn("approved_patch", artifact_types)
        self.assertIn("rollback_patch", artifact_types)
        self.assertIn("promotion_summary", artifact_types)
        self.assertEqual(_artifact_text(task_view, "rollback_patch"), README_ROLLBACK_DIFF)

    def test_reject_discard_requires_review_status(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase22-reject-status")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = create_live_codex_docs_only_task(
                project="operator",
                title="Queued docs task",
                goal="Make a docs-only README.md change",
            )
            with self.assertRaises(ValueError):
                reject_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(task_view["task"]["status"], "queued")

    def test_reject_discard_archives_rejected_patch_and_restores_worktree_readme_only(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase22-reject-discard")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task()
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_restore_path", return_value=CommandResult("git restore -- README.md", "", "", 0)
            ) as restore:
                rejected = reject_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(rejected["status"], "canceled")
        self.assertTrue(rejected["discarded"])
        restore.assert_called_once()
        self.assertEqual(restore.call_args.kwargs["target_path"], "README.md")
        self.assertEqual(_artifact_text(task_view, "rejected_patch"), README_DIFF)
        summary = _artifact_data(task_view, "discard_summary")
        self.assertTrue(summary["discarded"])
        self.assertFalse(summary["canonical_repo_touched"])

    def test_failed_reject_discard_remains_in_review_and_records_failure_artifact(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase22-reject-fails")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task()
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_restore_path", return_value=CommandResult("git restore -- README.md", "", "restore failed", 1)
            ):
                with self.assertRaises(RuntimeError):
                    reject_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(task_view["task"]["status"], "review")
        summary = _artifact_data(task_view, "discard_summary")
        self.assertFalse(summary["discarded"])

    def test_promotion_and_discard_preserve_artifacts_and_worktree(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase22-preserve")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            approve_task_id = _prepare_review_task("Approve preserve")
            before_approve = show_task(approve_task_id)
            approve_worktree = before_approve["runs"][0]["worktree_path"]
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_reverse_diff", return_value=CommandResult("git diff -R", README_ROLLBACK_DIFF, "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_check", return_value=CommandResult("git apply --check", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_patch", return_value=CommandResult("git apply", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                approve_task(approve_task_id)
            after_approve = show_task(approve_task_id)

            reject_task_id = _prepare_review_task("Reject preserve")
            before_reject = show_task(reject_task_id)
            reject_worktree = before_reject["runs"][0]["worktree_path"]
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_restore_path", return_value=CommandResult("git restore -- README.md", "", "", 0)
            ):
                reject_task(reject_task_id)
            after_reject = show_task(reject_task_id)

        self.assertEqual(after_approve["runs"][0]["worktree_path"], approve_worktree)
        self.assertGreater(len(after_approve["artifacts"]), len(before_approve["artifacts"]))
        self.assertEqual(after_reject["runs"][0]["worktree_path"], reject_worktree)
        self.assertGreater(len(after_reject["artifacts"]), len(before_reject["artifacts"]))

    def test_promotion_locks_are_released_on_success_and_failure(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase22-locks")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            success_task_id = _prepare_review_task("Success locks")
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_reverse_diff", return_value=CommandResult("git diff -R", README_ROLLBACK_DIFF, "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_check", return_value=CommandResult("git apply --check", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_patch", return_value=CommandResult("git apply", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                approve_task(success_task_id)
            with transaction() as conn:
                active_after_success = conn.execute("SELECT * FROM locks WHERE status = 'active'").fetchall()

            failure_task_id = _prepare_review_task("Failure locks")
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_reverse_diff", return_value=CommandResult("git diff -R", README_ROLLBACK_DIFF, "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_check", return_value=CommandResult("git apply --check", "", "patch failed", 1)
            ):
                with self.assertRaises(RuntimeError):
                    approve_task(failure_task_id)
            with transaction() as conn:
                active_after_failure = conn.execute("SELECT * FROM locks WHERE status = 'active'").fetchall()
            failed_task_view = show_task(failure_task_id)

        self.assertEqual(len(active_after_success), 0)
        self.assertEqual(len(active_after_failure), 0)
        self.assertEqual(failed_task_view["task"]["status"], "review")


if __name__ == "__main__":
    unittest.main()
