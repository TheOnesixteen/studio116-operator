import json
import os
import unittest
from pathlib import Path
from unittest import mock

from app.db import init_db, transaction
from app.locks import acquire_lock, release_lock
from app.models import CommandResult
from app.router import create_delegated_dry_run_task
from app.scheduler import run_next
from app.task_engine import show_task


def _reset_runtime(runtime_dir: str) -> str:
    db_path = f"{runtime_dir}/operator.db"
    if os.path.exists(db_path):
        os.unlink(db_path)
    return db_path


class DelegationDryRunTests(unittest.TestCase):
    def test_codex_dry_run_creates_packet_worktree_and_intended_command(self):
        runtime_dir = "/tmp/studio116-operator-test-delegation-codex"
        db_path = _reset_runtime(runtime_dir)
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            git_result = CommandResult("git worktree add", "", "", 0)
            with mock.patch("app.task_engine.create_worktree", return_value=git_result) as create_worktree:
                task_id = create_delegated_dry_run_task(
                    project="operator",
                    title="Docs dry run",
                    goal="Prepare a docs-only delegated dry run",
                    worker="codex",
                )
                result = run_next(task_id)

            task_view = show_task(task_id)
            run = task_view["runs"][0]
            packet_artifact = next(
                artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == "worker_packet"
            )
            packet = json.loads(Path(packet_artifact["path"]).read_text(encoding="utf-8"))
            with transaction() as conn:
                intended = conn.execute(
                    "SELECT * FROM worker_executions WHERE run_id = ? AND worker_name = 'codex'",
                    (run["id"],),
                ).fetchone()
                active_locks = conn.execute("SELECT * FROM locks WHERE status = 'active'").fetchall()

        self.assertTrue(result["task_succeeded"])
        self.assertEqual(result["overall_status"], "ok")
        self.assertEqual(run["worker_name"], "codex")
        self.assertEqual(run["run_type"], "delegated_dry_run")
        self.assertIn("/worktrees/", run["worktree_path"])
        self.assertTrue(run["branch_name"].startswith("operator/"))
        self.assertEqual(packet["worker"], "codex")
        self.assertEqual(packet["mode"], "dry_run")
        self.assertFalse(packet["read_only"])
        self.assertEqual(packet["worktree_path"], run["worktree_path"])
        self.assertIn("create_worktrees", packet["allowed_actions"])
        self.assertIn("deploy_to_production", packet["forbidden_actions"])
        self.assertIn("codex exec", intended["command"])
        self.assertIn('"launched": false', intended["metadata_json"])
        self.assertTrue(any(execution["worker_name"] == "codex" for execution in task_view["worker_executions"]))
        self.assertEqual(len(active_locks), 0)
        create_worktree.assert_called_once()

    def test_claude_dry_run_is_read_only_and_does_not_create_worktree(self):
        runtime_dir = "/tmp/studio116-operator-test-delegation-claude"
        db_path = _reset_runtime(runtime_dir)
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree") as create_worktree:
                task_id = create_delegated_dry_run_task(
                    project="operator",
                    title="Read-only review",
                    goal="Prepare a read-only review packet",
                    worker="claude_code",
                    read_only=True,
                )
                result = run_next(task_id)

            task_view = show_task(task_id)
            run = task_view["runs"][0]
            packet_artifact = next(
                artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == "worker_packet"
            )
            packet = json.loads(Path(packet_artifact["path"]).read_text(encoding="utf-8"))
            with transaction() as conn:
                intended = conn.execute(
                    "SELECT * FROM worker_executions WHERE run_id = ? AND worker_name = 'claude_code'",
                    (run["id"],),
                ).fetchone()

        self.assertTrue(result["task_succeeded"])
        self.assertEqual(run["worker_name"], "claude_code")
        self.assertIsNone(run["worktree_path"])
        self.assertIsNone(run["branch_name"])
        self.assertTrue(packet["read_only"])
        self.assertIsNone(packet["worktree_path"])
        self.assertIn("delegate_read_only", packet["allowed_actions"])
        self.assertIn("116studio-ai --read-only", intended["command"])
        create_worktree.assert_not_called()

    def test_gemini_dry_run_is_read_only_and_does_not_create_worktree(self):
        runtime_dir = "/tmp/studio116-operator-test-delegation-gemini"
        db_path = _reset_runtime(runtime_dir)
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree") as create_worktree:
                task_id = create_delegated_dry_run_task(
                    project="operator",
                    title="Gemini review",
                    goal="Prepare a read-only Gemini review packet",
                    worker="gemini_cli",
                )
                result = run_next(task_id)

            task_view = show_task(task_id)
            run = task_view["runs"][0]
            packet_artifact = next(
                artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == "worker_packet"
            )
            packet = json.loads(Path(packet_artifact["path"]).read_text(encoding="utf-8"))
            with transaction() as conn:
                intended = conn.execute(
                    "SELECT * FROM worker_executions WHERE run_id = ? AND worker_name = 'gemini_cli'",
                    (run["id"],),
                ).fetchone()

        self.assertTrue(result["task_succeeded"])
        self.assertEqual(run["worker_name"], "gemini_cli")
        self.assertIsNone(run["worktree_path"])
        self.assertIsNone(run["branch_name"])
        self.assertTrue(packet["read_only"])
        self.assertIsNone(packet["worktree_path"])
        self.assertIn("delegate_read_only", packet["allowed_actions"])
        self.assertIn("Do not modify files", intended["command"])
        create_worktree.assert_not_called()

    def test_one_writable_codex_lock_blocks_second_delegated_writer(self):
        runtime_dir = "/tmp/studio116-operator-test-delegation-lock"
        db_path = _reset_runtime(runtime_dir)
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            blocker_id = acquire_lock(lock_type="delegated_writer", resource_key="codex")
            try:
                task_id = create_delegated_dry_run_task(
                    project="operator",
                    title="Blocked docs dry run",
                    goal="Prepare a docs-only delegated dry run",
                    worker="codex",
                )
                with self.assertRaises(RuntimeError):
                    run_next(task_id)
                task = show_task(task_id)["task"]
                with transaction() as conn:
                    leaked_locks = conn.execute(
                        "SELECT * FROM locks WHERE status = 'active' AND id != ?",
                        (blocker_id,),
                    ).fetchall()
            finally:
                release_lock(blocker_id)

        self.assertEqual(task["status"], "failed")
        self.assertEqual(len(leaked_locks), 0)


if __name__ == "__main__":
    unittest.main()
