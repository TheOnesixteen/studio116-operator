import json
import os
import unittest
from pathlib import Path
from unittest import mock

from app.db import init_db
from app.models import CommandResult
from app.policies import live_codex_preflight_checks
from app.router import create_live_codex_docs_only_task
from app.scheduler import run_next
from app.task_engine import approve_task, reject_task, show_task


def _runtime(name: str) -> tuple[str, str]:
    runtime_dir = f"/tmp/{name}"
    db_path = f"{runtime_dir}/operator.db"
    if os.path.exists(db_path):
        os.unlink(db_path)
    return runtime_dir, db_path


MISSION_001_TARGETS = [
    "docs/ARCHITECTURE_REVIEW.md",
    "docs/IMPLEMENTATION_PLAN.md",
    "docs/TASK_BREAKDOWN.md",
]


def _success_mocks(*, changed_stdout: str = "README.md\n", diff_stdout: str = "diff --git a/README.md b/README.md\n"):
    return (
        mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)),
        mock.patch("app.task_engine.run_live_docs_only", return_value=CommandResult("codex exec", "ok", "", 0)),
        mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", diff_stdout, "", 0)),
        mock.patch("app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", changed_stdout, "", 0)),
        mock.patch("app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)),
    )


def _artifact_data(task_view: dict, artifact_type: str) -> dict:
    artifact = next(artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == artifact_type)
    return json.loads(Path(artifact["path"]).read_text(encoding="utf-8"))


def _check(preflight_data: dict, name: str) -> dict:
    return next(check for check in preflight_data["checks"] if check["name"] == name)


def _preflight_for(project: str, target_paths: list[str], *, worker: str = "codex") -> dict:
    repo_root = Path("/root/Projects/studio116-operator") if project == "operator" else Path("/root/Projects/redletters.tellthem.ai")
    checks = live_codex_preflight_checks(
        project=project,
        worker=worker,
        mode="live_codex_docs_only",
        target_paths=target_paths,
        repo_root=repo_root,
        worktree_path=Path("/root/Projects/studio116-operator/runtime/worktrees/task/codex"),
        command_cwd=Path("/root/Projects/studio116-operator/runtime/worktrees/task/codex"),
        active_delegated_writer_locks=0,
        goal="Make a docs-only change",
        constraints=[],
        worktree_ready=True,
    )
    return {"passed": all(check["passed"] for check in checks), "checks": checks, "allowed_targets": _check({"checks": checks}, "paths_are_policy_allowed")["details"]["allowed_targets"]}


class LiveCodexDocsOnlyTests(unittest.TestCase):
    def test_live_codex_success_stops_in_review_and_writes_artifacts(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-success")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            patches = _success_mocks()
            preflight_seen_before_launch = {"seen": False}

            def _codex_success(*, worktree_path, packet_path, timeout_seconds):
                preflight_seen_before_launch["seen"] = (packet_path.parent / "preflight_result.json").exists()
                return CommandResult("codex exec", "ok", "", 0)

            with patches[0], mock.patch("app.task_engine.run_live_docs_only", side_effect=_codex_success) as codex_run, patches[2], patches[3], patches[4]:
                task_id = create_live_codex_docs_only_task(
                    project="operator",
                    title="README live docs task",
                    goal="Make a docs-only README.md change",
                )
                result = run_next(task_id)
            task_view = show_task(task_id)
            preflight_data = _artifact_data(task_view, "preflight_result")

        artifact_types = {artifact["artifact_type"] for artifact in task_view["artifacts"]}
        run = task_view["runs"][0]
        self.assertTrue(result["task_succeeded"])
        self.assertTrue(result["stop_in_review"])
        self.assertEqual(task_view["task"]["status"], "review")
        self.assertEqual(run["status"], "review")
        self.assertIn("preflight_result", artifact_types)
        self.assertIn("worker_packet", artifact_types)
        self.assertIn("worker_result", artifact_types)
        self.assertIn("git_diff", artifact_types)
        self.assertIn("changed_files", artifact_types)
        self.assertIn("review_summary", artifact_types)
        self.assertIn("/worktrees/", run["worktree_path"])
        self.assertTrue(_check(preflight_data, "project_is_operator_or_known_writable")["passed"])
        self.assertTrue(_check(preflight_data, "repo_root_is_operator_or_project_repo")["passed"])
        codex_run.assert_called_once()
        self.assertTrue(preflight_seen_before_launch["seen"])

    def test_preflight_artifact_written_before_codex_launch_and_blocks_unknown_external_project(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-preflight")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_live_docs_only"
            ) as codex_run:
                task_id = create_live_codex_docs_only_task(
                    project="unknown_external",
                    title="Bad live docs task",
                    goal="Make a docs-only README.md change",
                )
                result = run_next(task_id)
            task_view = show_task(task_id)
            preflight_data = _artifact_data(task_view, "preflight_result")

        self.assertFalse(result["task_succeeded"])
        self.assertEqual(result["overall_status"], "failed")
        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertFalse(preflight_data["passed"])
        self.assertFalse(_check(preflight_data, "project_is_operator_or_known_writable")["passed"])
        self.assertFalse(_check(preflight_data, "external_project_write_preflight_authorized")["passed"])
        codex_run.assert_not_called()

    def test_redletters_docs_only_codex_passes_preflight_and_stops_in_review(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-redletters")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            patches = _success_mocks()
            with patches[0] as create_worktree, patches[1] as codex_run, patches[2], patches[3], patches[4]:
                task_id = create_live_codex_docs_only_task(
                    project="redletters",
                    title="RedLetters README docs",
                    goal="Make a docs-only README.md change",
                    target_paths=["README.md"],
                )
                result = run_next(task_id)
            task_view = show_task(task_id)
            preflight_data = _artifact_data(task_view, "preflight_result")

        self.assertTrue(result["task_succeeded"])
        self.assertEqual(task_view["task"]["status"], "review")
        self.assertTrue(_check(preflight_data, "project_is_operator_or_known_writable")["passed"])
        self.assertTrue(_check(preflight_data, "external_project_write_preflight_authorized")["passed"])
        self.assertTrue(_check(preflight_data, "external_project_deployment_not_allowed")["passed"])
        self.assertEqual(_check(preflight_data, "external_project_write_preflight_authorized")["details"]["deployment_allowed"], False)
        self.assertEqual(str(create_worktree.call_args.kwargs["repo_path"]), "/root/Projects/redletters.tellthem.ai")
        codex_run.assert_called_once()

    def test_redletters_mission_001_docs_targets_pass_preflight_and_post_run(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-redletters-mission-001")
        changed_stdout = "".join(f"{path}\n" for path in MISSION_001_TARGETS)
        diff_stdout = "".join(f"diff --git a/{path} b/{path}\n" for path in MISSION_001_TARGETS)
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            patches = _success_mocks(changed_stdout=changed_stdout, diff_stdout=diff_stdout)
            with patches[0], patches[1] as codex_run, patches[2], patches[3], patches[4]:
                task_id = create_live_codex_docs_only_task(
                    project="redletters",
                    title="RedLetters Mission 001",
                    goal="Create initial RedLetters planning docs",
                    target_paths=MISSION_001_TARGETS,
                )
                result = run_next(task_id)
            task_view = show_task(task_id)
            preflight_data = _artifact_data(task_view, "preflight_result")
            changed_data = _artifact_data(task_view, "changed_files")

        self.assertTrue(result["task_succeeded"])
        self.assertEqual(task_view["task"]["status"], "review")
        self.assertTrue(preflight_data["passed"])
        self.assertTrue(changed_data["passed"])
        self.assertEqual(preflight_data["target_paths"], MISSION_001_TARGETS)
        self.assertIn("docs/*.md", preflight_data["allowed_targets"])
        self.assertTrue(_check(preflight_data, "target_paths_within_project_write_policy_max")["passed"])
        codex_run.assert_called_once()

    def test_docs_glob_is_project_aware_and_requires_external_docs_only_policy(self):
        operator_preflight = _preflight_for("operator", ["docs/ARCHITECTURE_REVIEW.md"])
        redletters_preflight = _preflight_for("redletters", ["docs/ARCHITECTURE_REVIEW.md"])

        self.assertFalse(operator_preflight["passed"])
        self.assertFalse(_check(operator_preflight, "paths_are_policy_allowed")["passed"])
        self.assertNotIn("docs/*.md", operator_preflight["allowed_targets"])
        self.assertTrue(redletters_preflight["passed"])
        self.assertTrue(_check(redletters_preflight, "paths_are_policy_allowed")["passed"])
        self.assertIn("docs/*.md", redletters_preflight["allowed_targets"])

    def test_redletters_rejects_non_docs_app_code_target_before_launch(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-redletters-app")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_live_docs_only"
            ) as codex_run:
                task_id = create_live_codex_docs_only_task(
                    project="redletters",
                    title="RedLetters bad app target",
                    goal="Make an app code change",
                    target_paths=["app/main.py"],
                )
                result = run_next(task_id)
            task_view = show_task(task_id)
            preflight_data = _artifact_data(task_view, "preflight_result")

        self.assertFalse(result["task_succeeded"])
        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertFalse(_check(preflight_data, "target_paths_are_policy_allowed")["passed"])
        self.assertFalse(_check(preflight_data, "paths_are_markdown_docs")["passed"])
        self.assertFalse(_check(preflight_data, "paths_are_policy_allowed")["passed"])
        codex_run.assert_not_called()

    def test_redletters_rejects_env_target_before_launch(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-redletters-env")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_live_docs_only"
            ) as codex_run:
                task_id = create_live_codex_docs_only_task(
                    project="redletters",
                    title="RedLetters bad env target",
                    goal="Try to edit env file",
                    target_paths=["docs/.env"],
                )
                result = run_next(task_id)
            task_view = show_task(task_id)
            preflight_data = _artifact_data(task_view, "preflight_result")

        self.assertFalse(result["task_succeeded"])
        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertFalse(_check(preflight_data, "target_paths_are_policy_allowed")["passed"])
        self.assertFalse(_check(preflight_data, "paths_are_markdown_docs")["passed"])
        self.assertFalse(_check(preflight_data, "paths_are_policy_allowed")["passed"])
        self.assertFalse(_check(preflight_data, "no_hidden_files")["passed"])
        self.assertFalse(_check(preflight_data, "no_env_files")["passed"])
        codex_run.assert_not_called()

    def test_timeout_fails_and_preserves_worktree_record(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-timeout")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_live_docs_only",
                return_value=CommandResult("codex exec", "", "timeout", 124, timed_out=True),
            ):
                task_id = create_live_codex_docs_only_task(
                    project="operator",
                    title="Timeout docs task",
                    goal="Make a docs-only README.md change",
                )
                result = run_next(task_id)
            task_view = show_task(task_id)

        self.assertFalse(result["task_succeeded"])
        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertIn("/worktrees/", task_view["runs"][0]["worktree_path"])
        artifact_types = {artifact["artifact_type"] for artifact in task_view["artifacts"]}
        self.assertIn("preflight_result", artifact_types)
        self.assertIn("worker_result", artifact_types)

    def test_changed_files_validation_enforces_readme_only_post_run(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-changed-files")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_live_docs_only", return_value=CommandResult("codex exec", "ok", "", 0)
            ), mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", "diff", "", 0)), mock.patch(
                "app.task_engine.git_changed_files",
                return_value=CommandResult("git diff --name-only", "README.md\napp/main.py\n", "", 0),
            ), mock.patch(
                "app.task_engine.git_head",
                return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0),
            ):
                task_id = create_live_codex_docs_only_task(
                    project="operator",
                    title="Bad changed files task",
                    goal="Make a docs-only README.md change",
                )
                result = run_next(task_id)
            task_view = show_task(task_id)
            changed = next(artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == "changed_files")
            changed_data = json.loads(Path(changed["path"]).read_text(encoding="utf-8"))

        self.assertFalse(result["task_succeeded"])
        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertFalse(changed_data["passed"])
        self.assertTrue(any(check["name"] == "changed_files_are_policy_allowed" and not check["passed"] for check in changed_data["checks"]))

    def test_approve_and_reject_only_from_review(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-approve")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            patches = _success_mocks()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                task_id = create_live_codex_docs_only_task(
                    project="operator",
                    title="Approve docs task",
                    goal="Make a docs-only README.md change",
                )
                run_next(task_id)
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", "diff --git a/README.md b/README.md\n", "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_reverse_diff", return_value=CommandResult("git diff -R", "diff --git a/README.md b/README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_check", return_value=CommandResult("git apply --check", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_patch", return_value=CommandResult("git apply", "", "", 0)
            ), mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                approved = approve_task(task_id)
            with self.assertRaises(ValueError):
                reject_task(task_id)

        self.assertEqual(approved["status"], "done")
        self.assertTrue(approved["promoted"])
        self.assertTrue(approved["worktree_preserved"])

        runtime_dir, db_path = _runtime("studio116-operator-test-live-codex-reject")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            patches = _success_mocks()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                task_id = create_live_codex_docs_only_task(
                    project="operator",
                    title="Reject docs task",
                    goal="Make a docs-only README.md change",
                )
                run_next(task_id)
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", "diff --git a/README.md b/README.md\n", "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_restore_path", return_value=CommandResult("git restore -- README.md", "", "", 0)
            ):
                rejected = reject_task(task_id)

        self.assertEqual(rejected["status"], "canceled")
        self.assertTrue(rejected["discarded"])
        self.assertTrue(rejected["worktree_preserved"])


if __name__ == "__main__":
    unittest.main()
