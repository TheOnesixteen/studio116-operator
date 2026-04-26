import json
import os
import unittest
from pathlib import Path
from unittest import mock

from app.db import init_db
from app.models import CommandResult
from app.router import create_live_codex_docs_only_task
from app.scheduler import run_next
from app.task_engine import show_task


ROLLOUT_ITEM_NOISE = "failed to record rollout items"


def _runtime(name: str) -> tuple[str, str]:
    runtime_dir = f"/tmp/{name}"
    db_path = f"{runtime_dir}/operator.db"
    if os.path.exists(db_path):
        os.unlink(db_path)
    return runtime_dir, db_path


def _artifact_data(task_view: dict, artifact_type: str) -> dict:
    artifact = next(artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == artifact_type)
    return json.loads(Path(artifact["path"]).read_text(encoding="utf-8"))


class Phase27aCodexStderrNoiseTests(unittest.TestCase):
    def test_rollout_item_stderr_is_captured_but_non_blocking(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase27a-codex-stderr-noise")
        codex_stderr = f"{ROLLOUT_ITEM_NOISE}\n"

        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_live_docs_only",
                return_value=CommandResult("codex exec", "ok", codex_stderr, 0),
            ), mock.patch(
                "app.task_engine.git_diff",
                return_value=CommandResult("git diff", "diff --git a/README.md b/README.md\n", "", 0),
            ), mock.patch(
                "app.task_engine.git_changed_files",
                return_value=CommandResult("git diff --name-only", "README.md\n", "", 0),
            ), mock.patch(
                "app.task_engine.git_head",
                return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0),
            ):
                task_id = create_live_codex_docs_only_task(
                    project="operator",
                    title="Codex stderr noise docs task",
                    goal="Make a docs-only README.md change",
                )
                result = run_next(task_id)
            task_view = show_task(task_id)

        codex_execution = next(
            execution for execution in task_view["worker_executions"] if execution["worker_name"] == "codex"
        )
        worker_result = _artifact_data(task_view, "worker_result")
        review_summary = _artifact_data(task_view, "review_summary")
        changed_files = _artifact_data(task_view, "changed_files")

        self.assertTrue(result["ok"])
        self.assertTrue(result["stop_in_review"])
        self.assertEqual(task_view["task"]["status"], "review")
        self.assertIn(ROLLOUT_ITEM_NOISE, codex_execution["stderr"])
        self.assertEqual(worker_result["stderr"], codex_stderr)
        self.assertIn(ROLLOUT_ITEM_NOISE, worker_result["stderr"])
        self.assertEqual(worker_result["exit_code"], 0)
        self.assertEqual(review_summary["task_stops_in"], "review")
        self.assertEqual(review_summary["summary"], "Live Codex docs-only task is ready for Rusty review")
        self.assertNotIn(ROLLOUT_ITEM_NOISE, review_summary["summary"])
        self.assertTrue(changed_files["passed"])


if __name__ == "__main__":
    unittest.main()
