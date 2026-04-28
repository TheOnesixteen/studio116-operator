import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

from app.main import main
from app.project_registry import project_context_for_task
from app.task_engine import show_task


def _runtime(name: str) -> tuple[str, str]:
    runtime_dir = f"/tmp/{name}"
    db_path = f"{runtime_dir}/operator.db"
    if os.path.exists(db_path):
        os.unlink(db_path)
    return runtime_dir, db_path


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _run_cli_system_exit(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            main(argv)
        except SystemExit as exc:
            return int(exc.code), stdout.getvalue(), stderr.getvalue()
    return 0, stdout.getvalue(), stderr.getvalue()


def _write_registry(projects: dict) -> Path:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    with handle:
        yaml.safe_dump({"projects": projects}, handle, sort_keys=False)
    return Path(handle.name)


class Phase29ProjectAwareTaskIntakeTests(unittest.TestCase):
    def test_known_project_slug_attaches_project_context_to_metadata(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase29-known")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            exit_code, output, error = _run_cli(
                [
                    "task",
                    "create",
                    "--project",
                    "kairoke",
                    "--type",
                    "health_check",
                    "--title",
                    "Review Kairoke context",
                    "--goal",
                    "See project context attached to task",
                ]
            )
            task = show_task(output.strip())["task"]

        metadata = json.loads(task["metadata_json"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        self.assertEqual(metadata["project_context_source"], "registry/projects.yaml")
        self.assertEqual(metadata["project_context"]["slug"], "kairoke")
        self.assertEqual(metadata["project_context"]["repo_path"], "/root/Projects/kairoke.com")
        self.assertEqual(metadata["project_context"]["deployment_method"], "droplet_systemd")

    def test_unknown_project_slug_fails_with_helpful_message(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase29-unknown")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            exit_code, output, error = _run_cli(
                [
                    "task",
                    "create",
                    "--project",
                    "not-a-project",
                    "--type",
                    "health_check",
                    "--title",
                    "Unknown project",
                    "--goal",
                    "This should fail early",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(output, "")
        self.assertIn("Unknown project slug: not-a-project", error)
        self.assertIn("Run scripts/operator projects list to see known projects.", error)

    def test_allowed_agents_are_metadata_not_routing(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase29-routing")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            exit_code, output, error = _run_cli(
                [
                    "task",
                    "create",
                    "--project",
                    "operator",
                    "--type",
                    "delegated",
                    "--title",
                    "Delegated context",
                    "--goal",
                    "Confirm registry context is metadata only",
                    "--worker",
                    "codex",
                    "--delegation-mode",
                    "dry_run",
                ]
            )
            task = show_task(output.strip())["task"]

        metadata = json.loads(task["metadata_json"])
        routing = json.loads(task["routing_json"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        self.assertEqual(metadata["project_context"]["allowed_agents"], ["codex", "claude_code"])
        self.assertNotIn("project_context", routing)
        self.assertNotIn("allowed_agents", routing)
        self.assertEqual(routing["worker"], "codex")

    def test_task_create_without_project_preserves_existing_argparse_behavior(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase29-no-project")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            exit_code, output, error = _run_cli_system_exit(
                [
                    "task",
                    "create",
                    "--type",
                    "health_check",
                    "--title",
                    "No project",
                    "--goal",
                    "Project remains required by existing CLI",
                ]
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(output, "")
        self.assertIn("the following arguments are required: --project", error)
        self.assertNotIn("Unknown project slug", error)

    def test_project_context_does_not_require_repo_path_to_exist(self):
        registry_path = _write_registry(
            {
                "missingrepo": {
                    "slug": "missingrepo",
                    "name": "Missing Repo",
                    "repo_path": "/definitely/not/a/real/studio116/path",
                    "stack": ["python"],
                    "domains": [],
                    "services": [],
                    "allowed_agents": ["codex"],
                    "deployment_method": "manual",
                    "status": "planned",
                    "notes": "Valid registry context with an intentionally absent repo path.",
                }
            }
        )

        metadata = project_context_for_task("missingrepo", registry_path)

        self.assertEqual(metadata["project_context"]["repo_path"], "/definitely/not/a/real/studio116/path")
        self.assertEqual(metadata["project_context_source"], "registry/projects.yaml")


if __name__ == "__main__":
    unittest.main()
