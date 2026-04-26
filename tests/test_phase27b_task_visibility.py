import io
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from app.artifact_store import write_json_artifact
from app.db import init_db, transaction
from app.events import utc_now
from app.main import main
from app.task_engine import create_task, create_run, finish_run, transition_task


def _runtime(name: str) -> tuple[str, str]:
    runtime_dir = f"/tmp/{name}"
    db_path = f"{runtime_dir}/operator.db"
    if os.path.exists(db_path):
        os.unlink(db_path)
    return runtime_dir, db_path


def _run_cli(argv: list[str]) -> tuple[int, str]:
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = main(argv)
    return exit_code, stdout.getvalue()


def _set_task_status(task_id: str, status: str) -> None:
    now = utc_now()
    with transaction() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET status = ?, updated_at = ?, started_at = COALESCE(started_at, ?)
            WHERE id = ?
            """,
            (status, now, now, task_id),
        )


def _create_review_task() -> str:
    task_id = create_task(
        project="operator",
        task_type="delegated",
        title="Review docs task",
        goal="Review a docs-only change",
        routing={"worker": "codex", "delegation_mode": "live_codex_docs_only"},
    )
    _set_task_status(task_id, "review")
    run_id = create_run(task_id, worker_name="codex", run_type="delegated_live_codex_docs_only")
    finish_run(run_id, task_id=task_id, status="review", exit_code=0, summary="Live Codex docs-only task is ready for Rusty review")
    write_json_artifact(
        task_id=task_id,
        run_id=run_id,
        artifact_type="changed_files",
        label="Changed files",
        filename="changed_files.json",
        data={"changed_files": ["README.md"], "passed": True},
    )
    return task_id


def _create_failed_task() -> str:
    task_id = create_task(
        project="operator",
        task_type="delegated",
        title="Failed policy task",
        goal="Make a policy change",
        routing={"worker": "codex", "delegation_mode": "live_codex_policy_file_only"},
    )
    _set_task_status(task_id, "failed")
    run_id = create_run(task_id, worker_name="codex", run_type="delegated_live_codex_policy_file_only")
    finish_run(run_id, task_id=task_id, status="failed", exit_code=1, summary="Live Codex policy-file post-run validation failed")
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO worker_executions (
              id, run_id, worker_name, command, stdout, stderr, exit_code,
              started_at, completed_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "worker-exec-unsafe-output",
                run_id,
                "codex",
                "codex exec",
                "RAW_STDOUT_SHOULD_NOT_APPEAR",
                "SECRET_OR_NOISY_STDERR_SHOULD_NOT_APPEAR",
                1,
                utc_now(),
                utc_now(),
                "{}",
            ),
        )
    return task_id


def _create_running_task() -> str:
    task_id = create_task(
        project="operator",
        task_type="delegated",
        title="Running model task",
        goal="Make a model change",
        routing={"worker": "codex", "delegation_mode": "live_codex_model_file_only"},
    )
    transition_task(task_id, "planning")
    transition_task(task_id, "ready")
    transition_task(task_id, "running")
    create_run(task_id, worker_name="codex", run_type="delegated_live_codex_model_file_only")
    return task_id


class Phase27bTaskVisibilityTests(unittest.TestCase):
    def test_tasks_inbox_handles_empty_operator(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase27b-empty")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            exit_code, output = _run_cli(["tasks", "inbox"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.strip(), "No tasks found. Operator is idle.")

    def test_tasks_inbox_prints_actionable_human_readable_sections(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase27b-inbox")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            review_task_id = _create_review_task()
            failed_task_id = _create_failed_task()
            running_task_id = _create_running_task()
            queued_task_id = create_task(project="vps", task_type="health_check", title="Queued health check", goal="Inspect health")
            exit_code, output = _run_cli(["tasks", "inbox"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Task Inbox", output)
        self.assertIn("Counts by status", output)
        self.assertIn("queued: 1", output)
        self.assertIn("running: 1", output)
        self.assertIn("review: 1", output)
        self.assertIn("failed: 1", output)
        self.assertIn("Needs attention now", output)
        self.assertIn("REVIEW", output)
        self.assertIn("Review docs task", output)
        self.assertIn(review_task_id, output)
        self.assertIn("changed files: README.md", output)
        self.assertIn(f"scripts/operator task show {review_task_id}", output)
        self.assertIn(f"scripts/operator task approve {review_task_id}", output)
        self.assertIn(f"scripts/operator task reject {review_task_id}", output)
        self.assertIn("FAILED", output)
        self.assertIn(failed_task_id, output)
        self.assertIn("latest run: Live Codex policy-file post-run validation failed", output)
        self.assertIn("RUNNING", output)
        self.assertIn(running_task_id, output)
        self.assertIn("started:", output)
        self.assertIn("heartbeat:", output)
        self.assertIn("Queued", output)
        self.assertIn(queued_task_id, output)
        self.assertIn("Active locks", output)
        self.assertIn("none", output)

    def test_tasks_inbox_degrades_when_changed_files_artifact_is_missing(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase27b-missing-artifact")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = create_task(
                project="operator",
                task_type="delegated",
                title="Review without artifact",
                goal="Review missing artifact behavior",
                routing={"worker": "codex", "delegation_mode": "live_codex_docs_only"},
            )
            _set_task_status(task_id, "review")
            run_id = create_run(task_id, worker_name="codex", run_type="delegated_live_codex_docs_only")
            finish_run(run_id, task_id=task_id, status="review", exit_code=0, summary="Ready for review")
            exit_code, output = _run_cli(["tasks", "inbox"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Review without artifact", output)
        self.assertIn("changed files: unavailable", output)
        self.assertIn(f"scripts/operator task show {task_id}", output)

    def test_tasks_inbox_does_not_print_raw_worker_output(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase27b-safe-output")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            _create_failed_task()
            exit_code, output = _run_cli(["tasks", "inbox"])

        self.assertEqual(exit_code, 0)
        self.assertNotIn("RAW_STDOUT_SHOULD_NOT_APPEAR", output)
        self.assertNotIn("SECRET_OR_NOISY_STDERR_SHOULD_NOT_APPEAR", output)


if __name__ == "__main__":
    unittest.main()
