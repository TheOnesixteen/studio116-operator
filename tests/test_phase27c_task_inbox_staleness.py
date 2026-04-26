import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

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


def _timestamp_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _set_task_status_and_age(task_id: str, status: str, *, days_old: int) -> None:
    timestamp = _timestamp_days_ago(days_old)
    with transaction() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET status = ?, updated_at = ?, started_at = COALESCE(started_at, ?)
            WHERE id = ?
            """,
            (status, timestamp, timestamp, task_id),
        )


def _create_review_task(title: str, *, days_old: int) -> str:
    task_id = create_task(
        project="operator",
        task_type="delegated",
        title=title,
        goal="Review a docs-only change",
        routing={"worker": "codex", "delegation_mode": "live_codex_docs_only"},
    )
    _set_task_status_and_age(task_id, "review", days_old=days_old)
    run_id = create_run(task_id, worker_name="codex", run_type="delegated_live_codex_docs_only")
    finish_run(run_id, task_id=task_id, status="review", exit_code=0, summary="Ready for review")
    return task_id


def _create_failed_task(title: str, *, days_old: int) -> str:
    task_id = create_task(
        project="operator",
        task_type="delegated",
        title=title,
        goal="Make a policy change",
        routing={"worker": "codex", "delegation_mode": "live_codex_policy_file_only"},
    )
    _set_task_status_and_age(task_id, "failed", days_old=days_old)
    run_id = create_run(task_id, worker_name="codex", run_type="delegated_live_codex_policy_file_only")
    finish_run(run_id, task_id=task_id, status="failed", exit_code=1, summary="Policy validation failed")
    return task_id


def _create_stale_running_task() -> str:
    task_id = create_task(
        project="operator",
        task_type="delegated",
        title="Old running task",
        goal="Make a model change",
        routing={"worker": "codex", "delegation_mode": "live_codex_model_file_only"},
    )
    transition_task(task_id, "planning")
    transition_task(task_id, "ready")
    transition_task(task_id, "running")
    run_id = create_run(task_id, worker_name="codex", run_type="delegated_live_codex_model_file_only")
    old_timestamp = _timestamp_days_ago(5)
    with transaction() as conn:
        conn.execute(
            "UPDATE tasks SET updated_at = ?, started_at = ? WHERE id = ?",
            (old_timestamp, old_timestamp, task_id),
        )
        conn.execute(
            "UPDATE task_runs SET started_at = ?, heartbeat_at = ? WHERE id = ?",
            (old_timestamp, old_timestamp, run_id),
        )
    return task_id


def _insert_raw_worker_output(task_id: str) -> None:
    run_id = create_run(task_id, worker_name="codex", run_type="delegated_live_codex_docs_only")
    finish_run(run_id, task_id=task_id, status="failed", exit_code=1, summary="Safe failure summary")
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO worker_executions (
              id, run_id, worker_name, command, stdout, stderr, exit_code,
              started_at, completed_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "phase27c-raw-output",
                run_id,
                "codex",
                "codex exec",
                "RAW_STDOUT_SHOULD_NOT_APPEAR_27C",
                "SECRET_OR_NOISY_STDERR_SHOULD_NOT_APPEAR_27C",
                1,
                utc_now(),
                utc_now(),
                "{}",
            ),
        )


class Phase27cTaskInboxStalenessTests(unittest.TestCase):
    def test_fresh_unresolved_task_appears_in_needs_attention_now(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase27c-fresh")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _create_review_task("Fresh review task", days_old=1)
            exit_code, output = _run_cli(["tasks", "inbox"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Tasks untouched for 3+ days appear under Older unresolved work.", output)
        self.assertLess(output.index("Fresh review task"), output.index("\nOlder unresolved work\n"))
        self.assertIn(task_id, output)
        self.assertIn("age: 1d", output)

    def test_old_unresolved_task_appears_in_older_unresolved_work_with_age(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase27c-stale")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _create_failed_task("Old failed task", days_old=5)
            exit_code, output = _run_cli(["tasks", "inbox"])

        self.assertEqual(exit_code, 0)
        self.assertLess(output.index("\nOlder unresolved work\n"), output.index("Old failed task"))
        self.assertIn(f"- STALE FAILED {task_id}  Old failed task", output)
        self.assertIn("age: 5d", output)
        self.assertIn("updated:", output)

    def test_stale_review_still_shows_review_action_commands(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase27c-stale-review")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _create_review_task("Old review task", days_old=4)
            exit_code, output = _run_cli(["tasks", "inbox"])

        self.assertEqual(exit_code, 0)
        self.assertIn(f"scripts/operator task show {task_id}", output)
        self.assertIn(f"scripts/operator task approve {task_id}", output)
        self.assertIn(f"scripts/operator task reject {task_id}", output)

    def test_stale_running_task_uses_updated_at_for_staleness_and_shows_heartbeat(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase27c-running")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _create_stale_running_task()
            exit_code, output = _run_cli(["tasks", "inbox"])

        self.assertEqual(exit_code, 0)
        self.assertIn(f"- STALE RUNNING {task_id}  Old running task", output)
        self.assertIn("age: 5d", output)
        self.assertIn("heartbeat:", output)

    def test_raw_worker_stdout_and_stderr_remain_absent(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase27c-safe-output")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _create_failed_task("Noisy failed task", days_old=1)
            _insert_raw_worker_output(task_id)
            exit_code, output = _run_cli(["tasks", "inbox"])

        self.assertEqual(exit_code, 0)
        self.assertNotIn("RAW_STDOUT_SHOULD_NOT_APPEAR_27C", output)
        self.assertNotIn("SECRET_OR_NOISY_STDERR_SHOULD_NOT_APPEAR_27C", output)

    def test_empty_inbox_behavior_is_unchanged(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase27c-empty")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            exit_code, output = _run_cli(["tasks", "inbox"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.strip(), "No tasks found. Operator is idle.")

    def test_no_current_items_prints_nothing_needs_attention_message(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase27c-no-current")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            _create_failed_task("Only old failed task", days_old=6)
            exit_code, output = _run_cli(["tasks", "inbox"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Nothing needs attention right now.", output)
        self.assertIn("Older unresolved work", output)
        self.assertIn("Only old failed task", output)


if __name__ == "__main__":
    unittest.main()
