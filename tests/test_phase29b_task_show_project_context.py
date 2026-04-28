import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from app.db import init_db
from app.main import main
from app.task_engine import create_task, show_task


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


def _create_project_context_task() -> tuple[int, str, str]:
    return _run_cli(
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


class Phase29bTaskShowProjectContextTests(unittest.TestCase):
    def test_task_show_with_project_context_renders_readable_section(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase29b-readable")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            create_exit, task_id, create_error = _create_project_context_task()
            show_exit, output, show_error = _run_cli(["task", "show", task_id.strip()])

        self.assertEqual(create_exit, 0)
        self.assertEqual(create_error, "")
        self.assertEqual(show_exit, 0)
        self.assertEqual(show_error, "")
        self.assertIn("Task\n", output)
        self.assertIn(f"  id: {task_id.strip()}", output)
        self.assertIn("  title: Review Kairoke context", output)
        self.assertIn("  status: queued", output)
        self.assertIn("  project: kairoke", output)
        self.assertIn("Project context", output)
        self.assertIn("  slug: kairoke", output)
        self.assertIn("  name: Kairoke", output)
        self.assertIn("  repo_path: /root/Projects/kairoke.com", output)
        self.assertIn("  stack: flask, systemd, caddy, n8n", output)
        self.assertIn("  domains: kairoke.com", output)
        self.assertIn("  services: kairoke.service", output)
        self.assertIn("  allowed_agents: codex, claude_code, n8n", output)
        self.assertIn("  deployment_method: droplet_systemd", output)
        self.assertIn("  status: active", output)
        self.assertIn("  notes: AI karaoke platform. Song generation via Mureka API.", output)
        self.assertIn("  source: registry/projects.yaml", output)

    def test_task_show_without_project_context_remains_raw_json_only(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase29b-no-context")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = create_task(
                project="legacy",
                task_type="health_check",
                title="Legacy task",
                goal="Show old task behavior",
            )
            expected = json.dumps(show_task(task_id), indent=2, sort_keys=True) + "\n"
            show_exit, output, show_error = _run_cli(["task", "show", task_id])

        self.assertEqual(show_exit, 0)
        self.assertEqual(show_error, "")
        self.assertEqual(output, expected)
        self.assertNotIn("Project context", output)

    def test_project_context_fields_are_readable_not_only_raw_json(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase29b-fields")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            _, task_id, _ = _create_project_context_task()
            _, output, _ = _run_cli(["task", "show", task_id.strip()])

        readable_part = output.split("Raw task JSON", 1)[0]
        self.assertIn("  repo_path: /root/Projects/kairoke.com", readable_part)
        self.assertIn("  allowed_agents: codex, claude_code, n8n", readable_part)
        self.assertIn("  deployment_method: droplet_systemd", readable_part)

    def test_task_show_preserves_routing_json(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase29b-routing")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            _, task_id, _ = _create_project_context_task()
            task = show_task(task_id.strip())["task"]
            _, output, _ = _run_cli(["task", "show", task_id.strip()])

        self.assertEqual(json.loads(task["routing_json"]), {})
        raw_json = output.split("Raw task JSON\n", 1)[1]
        rendered_task = json.loads(raw_json)["task"]
        self.assertEqual(json.loads(rendered_task["routing_json"]), {})

    def test_task_show_preserves_raw_json_output(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase29b-raw-json")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            _, task_id, _ = _create_project_context_task()
            _, output, _ = _run_cli(["task", "show", task_id.strip()])

        self.assertIn("Raw task JSON\n", output)
        raw_json = output.split("Raw task JSON\n", 1)[1]
        rendered = json.loads(raw_json)
        metadata = json.loads(rendered["task"]["metadata_json"])
        self.assertEqual(metadata["project_context"]["slug"], "kairoke")


if __name__ == "__main__":
    unittest.main()
