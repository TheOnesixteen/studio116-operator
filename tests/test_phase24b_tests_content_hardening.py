import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.db import init_db
from app.models import CommandResult
from app.policies import validate_live_codex_tests_only_content
from app.router import create_live_codex_tests_only_task
from app.scheduler import run_next
from app.task_engine import approve_task, reject_task, show_task


TEST_PATH = "tests/test_phase24b_content.py"
TEST_DIFF = (
    "diff --git a/tests/test_phase24b_content.py b/tests/test_phase24b_content.py\n"
    "--- a/tests/test_phase24b_content.py\n"
    "+++ b/tests/test_phase24b_content.py\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)
SAFE_CONTENT = "import unittest\n\nclass SafeTest(unittest.TestCase):\n    def test_safe(self):\n        self.assertTrue(True)\n"


def _runtime(name: str) -> tuple[str, str]:
    runtime_dir = f"/tmp/{name}"
    db_path = f"{runtime_dir}/operator.db"
    if os.path.exists(db_path):
        os.unlink(db_path)
    return runtime_dir, db_path


def _write_test_file(worktree_path: Path, content: str) -> None:
    path = worktree_path / TEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _content_checks_for(content: str) -> list[dict]:
    with tempfile.TemporaryDirectory() as temp_dir:
        worktree_path = Path(temp_dir)
        _write_test_file(worktree_path, content)
        return validate_live_codex_tests_only_content(worktree_path, [TEST_PATH])


def _failed_check_names(checks: list[dict]) -> set[str]:
    return {check["name"] for check in checks if not check["passed"]}


def _prepare_review_task(*, file_content: str = SAFE_CONTENT) -> str:
    def _codex_success(*, worktree_path, packet_path, timeout_seconds):
        _write_test_file(worktree_path, file_content)
        return CommandResult("codex exec", "ok", "", 0)

    with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
        "app.task_engine.run_live_tests_only", side_effect=_codex_success
    ), mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", TEST_DIFF, "", 0)), mock.patch(
        "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", f"{TEST_PATH}\n", "", 0)
    ), mock.patch(
        "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
    ):
        task_id = create_live_codex_tests_only_task(
            project="operator",
            title="Phase 2.4b content hardening task",
            goal="Make a tests-only change",
            target_paths=[TEST_PATH],
        )
        run_next(task_id)
    return task_id


def _artifact_data(task_view: dict, artifact_type: str) -> dict:
    artifact = next(artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == artifact_type)
    return json.loads(Path(artifact["path"]).read_text(encoding="utf-8"))


class Phase24bTestsContentHardeningTests(unittest.TestCase):
    def test_content_hardening_allows_simple_unittest_content(self):
        checks = _content_checks_for(SAFE_CONTENT)
        self.assertEqual(_failed_check_names(checks), set())

    def test_content_hardening_rejects_network_import(self):
        checks = _content_checks_for("import requests\n")
        self.assertIn("test_content_imports_are_allowed", _failed_check_names(checks))

    def test_content_hardening_rejects_from_network_import(self):
        checks = _content_checks_for("from urllib.request import urlopen\n")
        self.assertIn("test_content_imports_are_allowed", _failed_check_names(checks))

    def test_content_hardening_rejects_subprocess_run_call(self):
        checks = _content_checks_for("import unittest\nimport subprocess\nsubprocess.run(['true'])\n")
        self.assertIn("test_content_calls_are_allowed", _failed_check_names(checks))

    def test_content_hardening_rejects_os_system_call(self):
        checks = _content_checks_for("import unittest\nimport os\nos.system('true')\n")
        self.assertIn("test_content_calls_are_allowed", _failed_check_names(checks))

    def test_content_hardening_rejects_live_shell_command_literal(self):
        checks = _content_checks_for("COMMAND = 'systemctl restart kairoke.service'\n")
        self.assertIn("test_content_has_no_live_command_literals", _failed_check_names(checks))

    def test_content_hardening_rejects_production_path_literal(self):
        checks = _content_checks_for("SECRET = '/etc/caddy/Caddyfile'\n")
        self.assertIn("test_content_has_no_production_path_literals", _failed_check_names(checks))

    def test_content_hardening_allows_tmp_and_operator_repo_path_literals(self):
        checks = _content_checks_for(
            "TMP = '/tmp/studio116-operator-test-safe'\n"
            "REPO = '/root/Projects/studio116-operator/tests/test_example.py'\n"
        )
        self.assertNotIn("test_content_has_no_production_path_literals", _failed_check_names(checks))

    def test_content_hardening_rejects_live_host_literal(self):
        checks = _content_checks_for("HOST = 'do.116.studio'\n")
        self.assertIn("test_content_has_no_live_host_literals", _failed_check_names(checks))

    def test_post_run_blocks_tests_only_task_with_unsafe_content(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase24b-postrun")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task(file_content="import requests\n")
            task_view = show_task(task_id)
            changed = _artifact_data(task_view, "changed_files")

        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertFalse(changed["passed"])
        self.assertTrue(
            any(check["name"] == "test_content_imports_are_allowed" and not check["passed"] for check in changed["checks"])
        )

    def test_approve_rechecks_and_blocks_unsafe_test_content(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase24b-approve")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task()
            task_view = show_task(task_id)
            _write_test_file(Path(task_view["runs"][0]["worktree_path"]), "import requests\n")
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", TEST_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", f"{TEST_PATH}\n", "", 0)
            ), mock.patch("app.task_engine.git_apply_check") as apply_check:
                with self.assertRaises(RuntimeError):
                    approve_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(task_view["task"]["status"], "review")
        apply_check.assert_not_called()
        preflight = _artifact_data(task_view, "promotion_preflight")
        self.assertFalse(preflight["passed"])
        self.assertTrue(
            any(check["name"] == "test_content_imports_are_allowed" and not check["passed"] for check in preflight["checks"])
        )

    def test_reject_can_discard_even_if_content_would_be_unsafe(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase24b-reject")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _prepare_review_task()
            task_view = show_task(task_id)
            _write_test_file(Path(task_view["runs"][0]["worktree_path"]), "import requests\n")
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", TEST_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", f"{TEST_PATH}\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_restore_path", return_value=CommandResult("git restore", "", "", 0)
            ):
                rejected = reject_task(task_id)

        self.assertEqual(rejected["status"], "canceled")


if __name__ == "__main__":
    unittest.main()
