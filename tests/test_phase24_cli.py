import os
import unittest
from unittest import mock

from app.main import main


def _runtime(name: str) -> tuple[str, str]:
    runtime_dir = f"/tmp/{name}"
    db_path = f"{runtime_dir}/operator.db"
    if os.path.exists(db_path):
        os.unlink(db_path)
    return runtime_dir, db_path


class Phase24CliTests(unittest.TestCase):
    def test_cli_accepts_gemini_cli_for_delegated_dry_run(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase24-cli-gemini")
        argv = [
            "task",
            "create",
            "--project",
            "operator",
            "--type",
            "delegated",
            "--title",
            "Gemini review",
            "--goal",
            "Prepare a read-only Gemini review packet",
            "--worker",
            "gemini_cli",
            "--delegation-mode",
            "dry_run",
        ]
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}), mock.patch(
            "app.main.create_delegated_dry_run_task", return_value="task-123"
        ) as create_dry_run_task, mock.patch("builtins.print") as print_mock:
            exit_code = main(argv)

        self.assertEqual(exit_code, 0)
        create_dry_run_task.assert_called_once_with(
            project="operator",
            title="Gemini review",
            goal="Prepare a read-only Gemini review packet",
            worker="gemini_cli",
            read_only=False,
            requested_by="Rusty",
        )
        print_mock.assert_called_with("task-123")

    def test_cli_accepts_live_codex_tests_only_delegation_mode(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase24-cli")
        argv = [
            "task",
            "create",
            "--project",
            "operator",
            "--type",
            "delegated",
            "--title",
            "Tests whitelist smoke",
            "--goal",
            "Make a tests-only change",
            "--worker",
            "codex",
            "--delegation-mode",
            "live_codex_tests_only",
            "--target-path",
            "tests/test_phase24_tests_whitelist.py",
        ]
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}), mock.patch(
            "app.main.create_live_codex_tests_only_task", return_value="task-123"
        ) as create_tests_task, mock.patch("builtins.print") as print_mock:
            exit_code = main(argv)

        self.assertEqual(exit_code, 0)
        create_tests_task.assert_called_once_with(
            project="operator",
            title="Tests whitelist smoke",
            goal="Make a tests-only change",
            target_paths=["tests/test_phase24_tests_whitelist.py"],
            requested_by="Rusty",
        )
        print_mock.assert_called_with("task-123")

    def test_cli_requires_codex_for_live_codex_tests_only(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase24-cli-worker")
        argv = [
            "task",
            "create",
            "--project",
            "operator",
            "--type",
            "delegated",
            "--title",
            "Bad worker",
            "--goal",
            "Make a tests-only change",
            "--worker",
            "claude_code",
            "--delegation-mode",
            "live_codex_tests_only",
        ]
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}), mock.patch(
            "app.main.create_live_codex_tests_only_task"
        ) as create_tests_task, mock.patch("sys.stderr"):
            exit_code = main(argv)

        self.assertEqual(exit_code, 1)
        create_tests_task.assert_not_called()


if __name__ == "__main__":
    unittest.main()
