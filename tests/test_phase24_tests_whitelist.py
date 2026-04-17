import json
import os
import unittest
from pathlib import Path
from unittest import mock

from app.db import init_db
from app.models import CommandResult
from app.policies import (
    live_codex_tests_only_allowed_targets,
    live_codex_tests_only_preflight_checks,
)
from app.router import create_live_codex_tests_only_task
from app.scheduler import run_next
from app.task_engine import approve_task, reject_task, show_task


TEST_DIFF = (
    "diff --git a/tests/test_phase24_tests_whitelist.py b/tests/test_phase24_tests_whitelist.py\n"
    "--- a/tests/test_phase24_tests_whitelist.py\n"
    "+++ b/tests/test_phase24_tests_whitelist.py\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)


def _runtime(name: str) -> tuple[str, str]:
    runtime_dir = f"/tmp/{name}"
    db_path = f"{runtime_dir}/operator.db"
    if os.path.exists(db_path):
        os.unlink(db_path)
    return runtime_dir, db_path


def _preflight_for(target_paths: list[str]) -> list[dict]:
    return live_codex_tests_only_preflight_checks(
        project="operator",
        worker="codex",
        mode="live_codex_tests_only",
        target_paths=target_paths,
        repo_root=Path("/root/Projects/studio116-operator"),
        worktree_path=Path("/root/Projects/studio116-operator/runtime/worktrees/task/codex"),
        command_cwd=Path("/root/Projects/studio116-operator/runtime/worktrees/task/codex"),
        active_delegated_writer_locks=0,
        goal="Make a tests-only change",
        constraints=[],
        worktree_ready=True,
    )


def _prepare_review_task(
    *,
    target_paths: list[str],
    changed_stdout: str,
    diff_stdout: str,
    title: str = "Phase 2.4a tests task",
) -> str:
    with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
        "app.task_engine.run_live_tests_only", return_value=CommandResult("codex exec", "ok", "", 0)
    ), mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", diff_stdout, "", 0)), mock.patch(
        "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", changed_stdout, "", 0)
    ), mock.patch(
        "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
    ):
        task_id = create_live_codex_tests_only_task(
            project="operator",
            title=title,
            goal="Make a tests-only change",
            target_paths=target_paths,
        )
        run_next(task_id)
    return task_id


def _artifact_data(task_view: dict, artifact_type: str) -> dict:
    artifact = next(artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == artifact_type)
    return json.loads(Path(artifact["path"]).read_text(encoding="utf-8"))


class Phase24TestsWhitelistTests(unittest.TestCase):
    def test_tests_whitelist_defaults_to_tests_pattern_if_policy_missing(self):
        with mock.patch("app.policies._read_yaml_list", return_value=set()):
            self.assertEqual(live_codex_tests_only_allowed_targets(), ["tests/test_*.py"])

    def test_tests_whitelist_loads_from_registry_policies_yaml(self):
        self.assertEqual(live_codex_tests_only_allowed_targets(), ["tests/test_*.py"])

    def test_preflight_passes_for_tests_test_py_target(self):
        checks = _preflight_for(["tests/test_phase24_tests_whitelist.py"])
        self.assertTrue(all(check["passed"] for check in checks))

    def test_preflight_rejects_app_code_target(self):
        checks = _preflight_for(["app/main.py"])
        self.assertTrue(any(check["name"] == "target_paths_are_policy_allowed" and not check["passed"] for check in checks))
        self.assertTrue(any(check["name"] == "paths_are_tests" and not check["passed"] for check in checks))

    def test_preflight_rejects_non_matching_tests_file(self):
        checks = _preflight_for(["tests/helpers.py"])
        self.assertTrue(any(check["name"] == "target_paths_are_policy_allowed" and not check["passed"] for check in checks))
        self.assertTrue(any(check["name"] == "paths_are_tests" and not check["passed"] for check in checks))

    def test_preflight_rejects_absolute_path(self):
        checks = _preflight_for(["/root/Projects/studio116-operator/tests/test_example.py"])
        self.assertTrue(any(check["name"] == "paths_are_repo_relative" and not check["passed"] for check in checks))

    def test_preflight_rejects_parent_traversal(self):
        checks = _preflight_for(["../tests/test_example.py"])
        self.assertTrue(any(check["name"] == "paths_are_repo_relative" and not check["passed"] for check in checks))

    def test_preflight_rejection_blocks_codex_launch(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase24-preflight-block")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_live_tests_only"
            ) as codex_run:
                task_id = create_live_codex_tests_only_task(
                    project="operator",
                    title="Bad tests target",
                    goal="Try app code",
                    target_paths=["app/main.py"],
                )
                result = run_next(task_id)
            task_view = show_task(task_id)

        self.assertFalse(result["task_succeeded"])
        self.assertEqual(task_view["task"]["status"], "failed")
        codex_run.assert_not_called()

    def test_post_run_rejects_app_code_changed_file(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase24-postrun-block")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task(
                target_paths=["tests/test_phase24_tests_whitelist.py"],
                changed_stdout="app/main.py\n",
                diff_stdout="diff --git a/app/main.py b/app/main.py\n",
            )
            task_view = show_task(task_id)
            changed = _artifact_data(task_view, "changed_files")

        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertFalse(changed["passed"])
        self.assertTrue(any(check["name"] == "changed_files_are_policy_allowed" and not check["passed"] for check in changed["checks"]))

    def test_post_run_allows_whitelisted_test_file(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase24-review")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task(
                target_paths=["tests/test_phase24_tests_whitelist.py"],
                changed_stdout="tests/test_phase24_tests_whitelist.py\n",
                diff_stdout=TEST_DIFF,
            )
            task_view = show_task(task_id)
            changed = _artifact_data(task_view, "changed_files")

        self.assertEqual(task_view["task"]["status"], "review")
        self.assertTrue(changed["passed"])

    def test_approve_promotes_whitelisted_test_diff(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase24-approve")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task(
                target_paths=["tests/test_phase24_tests_whitelist.py"],
                changed_stdout="tests/test_phase24_tests_whitelist.py\n",
                diff_stdout=TEST_DIFF,
            )
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", TEST_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files",
                return_value=CommandResult("git diff --name-only", "tests/test_phase24_tests_whitelist.py\n", "", 0),
            ), mock.patch(
                "app.task_engine.git_reverse_diff", return_value=CommandResult("git diff -R", TEST_DIFF, "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_check", return_value=CommandResult("git apply --check", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_patch", return_value=CommandResult("git apply", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                approved = approve_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(approved["status"], "done")
        self.assertEqual(task_view["task"]["status"], "done")

    def test_approve_blocks_non_whitelisted_changed_file_and_remains_in_review(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase24-approve-block")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task(
                target_paths=["tests/test_phase24_tests_whitelist.py"],
                changed_stdout="tests/test_phase24_tests_whitelist.py\n",
                diff_stdout=TEST_DIFF,
            )
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", "diff", "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "registry/policies.yaml\n", "", 0)
            ):
                with self.assertRaises(RuntimeError):
                    approve_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(task_view["task"]["status"], "review")
        preflight = _artifact_data(task_view, "promotion_preflight")
        self.assertFalse(preflight["passed"])

    def test_reject_discards_validated_test_file(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase24-reject")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task(
                target_paths=["tests/test_phase24_tests_whitelist.py"],
                changed_stdout="tests/test_phase24_tests_whitelist.py\n",
                diff_stdout=TEST_DIFF,
            )
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", TEST_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files",
                return_value=CommandResult("git diff --name-only", "tests/test_phase24_tests_whitelist.py\n", "", 0),
            ), mock.patch(
                "app.task_engine.git_restore_path", return_value=CommandResult("git restore", "", "", 0)
            ) as restore:
                rejected = reject_task(task_id)
            task_view = show_task(task_id)
            summary = _artifact_data(task_view, "discard_summary")

        self.assertEqual(rejected["status"], "canceled")
        restore.assert_called_once()
        self.assertEqual(restore.call_args.kwargs["target_path"], "tests/test_phase24_tests_whitelist.py")
        self.assertTrue(summary["discarded"])


if __name__ == "__main__":
    unittest.main()
