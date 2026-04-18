import json
import os
import unittest
from pathlib import Path
from unittest import mock

from app.db import init_db
from app.main import main
from app.models import CommandResult
from app.policies import (
    live_codex_policy_file_allowed_targets,
    live_codex_policy_file_preflight_checks,
    validate_live_codex_policy_file_content,
)
from app.router import create_live_codex_policy_file_task
from app.scheduler import run_next
from app.task_engine import approve_task, reject_task, show_task


POLICY_PATH = "app/policies.py"
POLICY_DIFF = (
    "diff --git a/app/policies.py b/app/policies.py\n"
    "--- a/app/policies.py\n"
    "+++ b/app/policies.py\n"
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


def _safe_policy_content() -> str:
    return Path("app/policies.py").read_text(encoding="utf-8")


def _write_policy_file(worktree_path: Path, content: str) -> None:
    path = worktree_path / POLICY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _preflight_for(target_paths: list[str]) -> list[dict]:
    return live_codex_policy_file_preflight_checks(
        project="operator",
        worker="codex",
        mode="live_codex_policy_file_only",
        target_paths=target_paths,
        repo_root=Path("/root/Projects/studio116-operator"),
        worktree_path=Path("/root/Projects/studio116-operator/runtime/worktrees/task/codex"),
        command_cwd=Path("/root/Projects/studio116-operator/runtime/worktrees/task/codex"),
        active_delegated_writer_locks=0,
        goal="Make a policy-file-only change",
        constraints=[],
        worktree_ready=True,
    )


def _failed_check_names(checks: list[dict]) -> set[str]:
    return {check["name"] for check in checks if not check["passed"]}


def _prepare_review_task(*, changed_stdout: str = f"{POLICY_PATH}\n", file_content: str | None = None) -> str:
    content = file_content if file_content is not None else _safe_policy_content()
    changed_paths = [line.strip() for line in changed_stdout.splitlines() if line.strip()]

    def _codex_success(*, worktree_path, packet_path, timeout_seconds):
        for changed_path in changed_paths:
            if changed_path == POLICY_PATH:
                _write_policy_file(worktree_path, content)
        return CommandResult("codex exec", "ok", "", 0)

    with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
        "app.task_engine.run_codex_live_policy_file", side_effect=_codex_success
    ), mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", POLICY_DIFF, "", 0)), mock.patch(
        "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", changed_stdout, "", 0)
    ), mock.patch(
        "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
    ):
        task_id = create_live_codex_policy_file_task(
            project="operator",
            title="Phase 2.5a policy file task",
            goal="Make a policy-file-only change",
            target_paths=[POLICY_PATH],
        )
        run_next(task_id)
    return task_id


def _artifact_data(task_view: dict, artifact_type: str) -> dict:
    artifact = next(artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == artifact_type)
    return json.loads(Path(artifact["path"]).read_text(encoding="utf-8"))


class Phase25aPolicyFileLaneTests(unittest.TestCase):
    def test_policy_file_whitelist_loads_from_registry(self):
        self.assertEqual(live_codex_policy_file_allowed_targets(), [POLICY_PATH])

    def test_preflight_passes_for_app_policies_py(self):
        self.assertEqual(_failed_check_names(_preflight_for([POLICY_PATH])), set())

    def test_preflight_rejects_other_app_files(self):
        for target in ("app/main.py", "app/router.py", "app/task_engine.py"):
            failed = _failed_check_names(_preflight_for([target]))
            self.assertIn("paths_are_policy_file", failed)
            self.assertIn("target_paths_are_policy_allowed", failed)

    def test_preflight_rejects_multiple_targets_absolute_and_parent_traversal(self):
        self.assertIn("path_count_exactly_1", _failed_check_names(_preflight_for([POLICY_PATH, "app/main.py"])))
        self.assertIn("paths_are_repo_relative", _failed_check_names(_preflight_for(["/root/Projects/studio116-operator/app/policies.py"])))
        self.assertIn("paths_are_repo_relative", _failed_check_names(_preflight_for(["../app/policies.py"])))

    def test_content_hardening_allows_current_app_policies_py(self):
        checks = validate_live_codex_policy_file_content(Path("."), [POLICY_PATH])
        self.assertEqual(_failed_check_names(checks), set())

    def test_content_hardening_rejects_dangerous_import_call_and_missing_symbol(self):
        dangerous_import = _safe_policy_content() + "\nimport subprocess\n"
        with mock.patch("pathlib.Path.read_text", return_value=dangerous_import):
            checks = validate_live_codex_policy_file_content(Path("."), [POLICY_PATH])
        self.assertIn("policy_file_content_imports_are_allowed", _failed_check_names(checks))

        dangerous_call = _safe_policy_content() + "\nimport os\nos.system('true')\n"
        with mock.patch("pathlib.Path.read_text", return_value=dangerous_call):
            checks = validate_live_codex_policy_file_content(Path("."), [POLICY_PATH])
        self.assertIn("policy_file_content_calls_are_allowed", _failed_check_names(checks))

        missing_symbol = _safe_policy_content().replace("def assert_phase1_allowed", "def assert_phase1_missing", 1)
        with mock.patch("pathlib.Path.read_text", return_value=missing_symbol):
            checks = validate_live_codex_policy_file_content(Path("."), [POLICY_PATH])
        self.assertIn("policy_file_content_required_symbols_exist", _failed_check_names(checks))

    def test_post_run_allows_only_app_policies_py_and_stops_in_review(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase25a-review")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task()
            task_view = show_task(task_id)
            changed = _artifact_data(task_view, "changed_files")

        self.assertEqual(task_view["task"]["status"], "review")
        self.assertTrue(changed["passed"])

    def test_post_run_rejects_non_policy_file_change(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase25a-postrun-block")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task(changed_stdout="app/router.py\n")
            task_view = show_task(task_id)
            changed = _artifact_data(task_view, "changed_files")

        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertFalse(changed["passed"])
        self.assertTrue(any(check["name"] == "changed_files_are_policy_allowed" and not check["passed"] for check in changed["checks"]))

    def test_approve_promotes_policy_file_patch_when_clean(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase25a-approve")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task()
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", POLICY_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", f"{POLICY_PATH}\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_reverse_diff", return_value=CommandResult("git diff -R", POLICY_DIFF, "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_check", return_value=CommandResult("git apply --check", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_patch", return_value=CommandResult("git apply", "", "", 0)
            ) as apply_patch, mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                approved = approve_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(approved["status"], "done")
        self.assertEqual(task_view["task"]["status"], "done")
        apply_patch.assert_called_once()

    def test_approve_stale_policy_file_patch_remains_in_review_with_recovery_context(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase25a-stale")
        canonical_context = "diff --git a/app/policies.py b/app/policies.py\n"
        apply_failure = "patch failed: app/policies.py:54\npatch does not apply\n"
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task()
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", POLICY_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", f"{POLICY_PATH}\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_reverse_diff", return_value=CommandResult("git diff -R", POLICY_DIFF, "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_check", return_value=CommandResult("git apply --check", "", apply_failure, 1)
            ), mock.patch("app.task_engine.git_apply_patch") as apply_patch, mock.patch(
                "app.task_engine.git_head",
                side_effect=[
                    CommandResult("git rev-parse HEAD", "review123\n", "", 0),
                    CommandResult("git rev-parse HEAD", "canonical456\n", "", 0),
                ],
            ), mock.patch(
                "app.task_engine.git_diff_against_ref",
                return_value=CommandResult("git diff review123 -- app/policies.py", canonical_context, "", 0),
            ):
                with self.assertRaises(RuntimeError):
                    approve_task(task_id)
            task_view = show_task(task_id)
            preflight = _artifact_data(task_view, "promotion_preflight")

        self.assertEqual(task_view["task"]["status"], "review")
        apply_patch.assert_not_called()
        self.assertFalse(preflight["passed"])
        self.assertIn("policy-file promotion blocked", preflight["summary"])
        self.assertIn("fresh live_codex_policy_file_only task", preflight["recommended_next_action"])
        self.assertTrue(preflight["stale_patch_recovery"]["target_file_drifted_since_review_started"])
        self.assertEqual(preflight["stale_patch_recovery"]["canonical_target_diff"]["stdout"], canonical_context)

    def test_reject_discards_policy_file_patch(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase25a-reject")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task()
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", POLICY_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", f"{POLICY_PATH}\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_restore_path", return_value=CommandResult("git restore", "", "", 0)
            ) as restore:
                rejected = reject_task(task_id)

        self.assertEqual(rejected["status"], "canceled")
        restore.assert_called_once()
        self.assertEqual(restore.call_args.kwargs["target_path"], POLICY_PATH)

    def test_cli_accepts_live_codex_policy_file_only_mode(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase25a-cli")
        argv = [
            "task",
            "create",
            "--project",
            "operator",
            "--type",
            "delegated",
            "--title",
            "Policy file change",
            "--goal",
            "Make a policy-file-only change",
            "--worker",
            "codex",
            "--delegation-mode",
            "live_codex_policy_file_only",
            "--target-path",
            POLICY_PATH,
        ]
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}), mock.patch(
            "app.main.create_live_codex_policy_file_task", return_value="task-123"
        ) as create_task, mock.patch("builtins.print") as print_mock:
            exit_code = main(argv)

        self.assertEqual(exit_code, 0)
        create_task.assert_called_once_with(
            project="operator",
            title="Policy file change",
            goal="Make a policy-file-only change",
            target_paths=[POLICY_PATH],
            requested_by="Rusty",
        )
        print_mock.assert_called_with("task-123")

    def test_cli_requires_codex_for_live_codex_policy_file_only_mode(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase25a-cli-worker")
        argv = [
            "task",
            "create",
            "--project",
            "operator",
            "--type",
            "delegated",
            "--title",
            "Policy file change",
            "--goal",
            "Make a policy-file-only change",
            "--worker",
            "claude_code",
            "--delegation-mode",
            "live_codex_policy_file_only",
        ]
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}), mock.patch(
            "app.main.create_live_codex_policy_file_task"
        ) as create_task, mock.patch("sys.stderr"):
            exit_code = main(argv)

        self.assertEqual(exit_code, 1)
        create_task.assert_not_called()


if __name__ == "__main__":
    unittest.main()
