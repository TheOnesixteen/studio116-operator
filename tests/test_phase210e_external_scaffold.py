import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from app.db import init_db, transaction
from app.main import main
from app.models import CommandResult
from app.policies import live_codex_model_file_preflight_checks, live_codex_scaffold_only_preflight_checks
from app.router import create_live_codex_docs_only_task, create_live_codex_model_file_task, create_live_codex_scaffold_only_task
from app.scheduler import run_next
from app.task_engine import approve_task, reject_task, show_task


README_DIFF = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n"
README_ROLLBACK_DIFF = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-new\n+old\n"
SCAFFOLD_TARGETS = ["app/__init__.py", "app/config.py", "app/routes.py"]
SCAFFOLD_CHANGED_STDOUT = "".join(f"{path}\n" for path in SCAFFOLD_TARGETS)
SCAFFOLD_DIFF = "".join(f"diff --git a/{path} b/{path}\n" for path in SCAFFOLD_TARGETS)
REQUIREMENTS_DIFF = (
    "diff --git a/requirements.txt b/requirements.txt\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/requirements.txt\n"
    "@@ -0,0 +1,2 @@\n"
    "+Flask>=3.0,<4\n"
    "+pytest>=8,<9\n"
)


def _runtime(name: str) -> tuple[str, str]:
    runtime_dir = f"/tmp/{name}"
    db_path = f"{runtime_dir}/operator.db"
    if os.path.exists(db_path):
        os.unlink(db_path)
    return runtime_dir, db_path


def _artifact_data(task_view: dict, artifact_type: str) -> dict:
    artifact = next(artifact for artifact in task_view["artifacts"] if artifact["artifact_type"] == artifact_type)
    return json.loads(Path(artifact["path"]).read_text(encoding="utf-8"))


def _check(data: dict, name: str) -> dict:
    return next(check for check in data["checks"] if check["name"] == name)


def _failed_check_names(checks: list[dict]) -> set[str]:
    return {check["name"] for check in checks if not check["passed"]}


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _redletters_scaffold_preflight(target_paths: list[str], *, worker: str = "codex") -> list[dict]:
    return live_codex_scaffold_only_preflight_checks(
        project="redletters",
        worker=worker,
        mode="live_codex_scaffold_only",
        target_paths=target_paths,
        repo_root=Path("/root/Projects/redletters.tellthem.ai"),
        worktree_path=Path("/root/Projects/studio116-operator/runtime/worktrees/task/codex"),
        command_cwd=Path("/root/Projects/studio116-operator/runtime/worktrees/task/codex"),
        active_delegated_writer_locks=0,
        goal="Create a safe scaffold",
        constraints=[],
        worktree_ready=True,
    )


def _redletters_review_task() -> str:
    with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
        "app.task_engine.run_live_docs_only", return_value=CommandResult("codex exec", "ok", "", 0)
    ), mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
        "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
    ), mock.patch(
        "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
    ):
        task_id = create_live_codex_docs_only_task(
            project="redletters",
            title="RedLetters external review",
            goal="Make a docs-only README.md change",
            target_paths=["README.md"],
        )
        run_next(task_id)
    return task_id


class Phase210eExternalScaffoldTests(unittest.TestCase):
    def test_external_approve_promotes_to_external_canonical_repo(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase210e-external-approve")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _redletters_review_task()
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_reverse_diff", return_value=CommandResult("git diff -R", README_ROLLBACK_DIFF, "", 0)
            ), mock.patch(
                "app.task_engine.git_apply_check", return_value=CommandResult("git apply --check", "", "", 0)
            ) as apply_check, mock.patch(
                "app.task_engine.git_apply_patch", return_value=CommandResult("git apply", "", "", 0)
            ) as apply_patch, mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                approved = approve_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(approved["status"], "done")
        self.assertEqual(task_view["task"]["status"], "done")
        self.assertEqual(str(apply_check.call_args.kwargs["repo_path"]), "/root/Projects/redletters.tellthem.ai")
        self.assertEqual(str(apply_patch.call_args.kwargs["repo_path"]), "/root/Projects/redletters.tellthem.ai")
        summary = _artifact_data(task_view, "promotion_summary")
        self.assertEqual(summary["canonical_repo_path"], "/root/Projects/redletters.tellthem.ai")
        self.assertFalse(summary["commit_created"])
        self.assertFalse(summary["merged"])
        self.assertFalse(summary["pushed"])

    def test_external_reject_discards_worktree_without_touching_canonical_repo(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase210e-external-reject")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _redletters_review_task()
            with mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", README_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files", return_value=CommandResult("git diff --name-only", "README.md\n", "", 0)
            ), mock.patch(
                "app.task_engine.git_restore_path", return_value=CommandResult("git restore -- README.md", "", "", 0)
            ) as restore:
                rejected = reject_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(rejected["status"], "canceled")
        self.assertEqual(task_view["task"]["status"], "canceled")
        restore.assert_called_once()
        summary = _artifact_data(task_view, "discard_summary")
        self.assertFalse(summary["canonical_repo_touched"])

    def test_unknown_external_project_review_fails(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase210e-unknown-review")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            task_id = _redletters_review_task()
            with transaction() as conn:
                conn.execute("UPDATE tasks SET project = ? WHERE id = ?", ("unknown_external", task_id))
            with self.assertRaises(PermissionError):
                approve_task(task_id)
            task_view = show_task(task_id)

        self.assertEqual(task_view["task"]["status"], "review")

    def test_redletters_scaffold_preflight_passes_and_launches_codex(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase210e-scaffold-pass")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_live_scaffold_only", return_value=CommandResult("codex exec", "ok", "", 0)
            ) as codex_run, mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", SCAFFOLD_DIFF, "", 0)), mock.patch(
                "app.task_engine.git_changed_files",
                return_value=CommandResult("git diff --name-only", SCAFFOLD_CHANGED_STDOUT, "", 0),
            ), mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                task_id = create_live_codex_scaffold_only_task(
                    project="redletters",
                    title="RedLetters scaffold",
                    goal="Create initial Flask scaffold files",
                    target_paths=SCAFFOLD_TARGETS,
                )
                result = run_next(task_id)
            task_view = show_task(task_id)
            preflight = _artifact_data(task_view, "preflight_result")

        self.assertTrue(result["task_succeeded"])
        self.assertEqual(task_view["task"]["status"], "review")
        self.assertTrue(preflight["passed"])
        self.assertTrue(_check(preflight, "project_is_known_writable")["passed"])
        self.assertTrue(_check(preflight, "external_project_deployment_not_allowed")["passed"])
        codex_run.assert_called_once()

    def test_redletters_scaffold_blocks_ai_generation_env_and_deploy_targets(self):
        blocked_cases = {
            "app/ai_generation.py": {"paths_are_scaffold_allowed", "target_paths_are_policy_allowed"},
            ".env": {"paths_are_scaffold_allowed", "no_hidden_files", "no_env_files", "no_deploy_config_system_files"},
            "deploy/release.sh": {"paths_are_scaffold_allowed", "no_deploy_config_system_files"},
        }
        for target, expected_failures in blocked_cases.items():
            with self.subTest(target=target):
                failed = _failed_check_names(_redletters_scaffold_preflight([target]))
                self.assertTrue(expected_failures.issubset(failed))

    def test_unknown_project_scaffold_preflight_fails(self):
        checks = live_codex_scaffold_only_preflight_checks(
            project="unknown_external",
            worker="codex",
            mode="live_codex_scaffold_only",
            target_paths=["app/routes.py"],
            repo_root=Path("/root/Projects/redletters.tellthem.ai"),
            worktree_path=Path("/root/Projects/studio116-operator/runtime/worktrees/task/codex"),
            command_cwd=Path("/root/Projects/studio116-operator/runtime/worktrees/task/codex"),
            active_delegated_writer_locks=0,
            goal="Create a safe scaffold",
            constraints=[],
            worktree_ready=True,
        )

        self.assertIn("project_is_known_writable", _failed_check_names(checks))
        self.assertIn("external_project_write_preflight_authorized", _failed_check_names(checks))

    def test_redletters_model_file_external_parity_allows_single_scaffold_target(self):
        checks = live_codex_model_file_preflight_checks(
            project="redletters",
            worker="codex",
            mode="live_codex_model_file_only",
            target_paths=["app/routes.py"],
            repo_root=Path("/root/Projects/redletters.tellthem.ai"),
            worktree_path=Path("/root/Projects/studio116-operator/runtime/worktrees/task/codex"),
            command_cwd=Path("/root/Projects/studio116-operator/runtime/worktrees/task/codex"),
            active_delegated_writer_locks=0,
            goal="Create one scaffold code file",
            constraints=[],
            worktree_ready=True,
        )

        self.assertEqual(_failed_check_names(checks), set())

    def test_redletters_model_file_external_run_writes_completion_artifacts(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase210e-model-external-artifacts")

        def _codex_success(*, worktree_path, packet_path, timeout_seconds):
            self.assertEqual(Path(packet_path).name, "worker_packet.json")
            self.assertTrue(str(worktree_path).endswith("/codex"))
            requirements = Path(worktree_path) / "requirements.txt"
            requirements.parent.mkdir(parents=True, exist_ok=True)
            requirements.write_text("Flask>=3.0,<4\npytest>=8,<9\n", encoding="utf-8")
            return CommandResult("codex exec", "ok", "", 0)

        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_codex_live_model_file", side_effect=_codex_success
            ) as codex_run, mock.patch(
                "app.task_engine.git_diff", return_value=CommandResult("git diff", REQUIREMENTS_DIFF, "", 0)
            ), mock.patch(
                "app.task_engine.git_changed_files",
                return_value=CommandResult("git diff --name-only", "requirements.txt\n", "", 0),
            ), mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                task_id = create_live_codex_model_file_task(
                    project="redletters",
                    title="RedLetters requirements",
                    goal="Create requirements.txt only",
                    target_paths=["requirements.txt"],
                )
                result = run_next(task_id)
            task_view = show_task(task_id)
            artifact_types = {artifact["artifact_type"] for artifact in task_view["artifacts"]}
            changed = _artifact_data(task_view, "changed_files")
            review = _artifact_data(task_view, "review_summary")

        self.assertTrue(result["task_succeeded"])
        self.assertEqual(task_view["task"]["status"], "review")
        self.assertIn("worker_result", artifact_types)
        self.assertIn("git_diff", artifact_types)
        self.assertIn("changed_files", artifact_types)
        self.assertIn("review_summary", artifact_types)
        self.assertEqual(changed["changed_files"], ["requirements.txt"])
        self.assertTrue(changed["passed"])
        self.assertTrue(_check(changed, "changed_file_count_within_project_write_policy_max")["passed"])
        self.assertEqual(review["task_stops_in"], "review")
        codex_run.assert_called_once()

    def test_redletters_model_file_external_no_change_fails_not_running(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase210e-model-external-no-change")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_codex_live_model_file", return_value=CommandResult("codex exec", "ok", "", 0)
            ), mock.patch("app.task_engine.git_diff", return_value=CommandResult("git diff", "", "", 0)), mock.patch(
                "app.task_engine.git_changed_files",
                return_value=CommandResult("git diff --name-only", "", "", 0),
            ), mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                task_id = create_live_codex_model_file_task(
                    project="redletters",
                    title="RedLetters empty requirements attempt",
                    goal="Create requirements.txt only",
                    target_paths=["requirements.txt"],
                )
                result = run_next(task_id)
            task_view = show_task(task_id)
            changed = _artifact_data(task_view, "changed_files")
            review = _artifact_data(task_view, "review_summary")

        self.assertFalse(result["task_succeeded"])
        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertFalse(changed["passed"])
        self.assertEqual(review["task_stops_in"], "failed")
        self.assertIn("no changes", result["summary"])

    def test_redletters_model_file_interruption_marks_task_and_run_failed(self):
        runtime_dir, db_path = _runtime("studio116-operator-test-phase210e-model-external-interrupted")
        with mock.patch.dict(os.environ, {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path}):
            init_db()
            with mock.patch("app.task_engine.create_worktree", return_value=CommandResult("git worktree add", "", "", 0)), mock.patch(
                "app.task_engine.run_codex_live_model_file", side_effect=KeyboardInterrupt("interrupted")
            ), mock.patch(
                "app.task_engine.git_head", return_value=CommandResult("git rev-parse HEAD", "abc123\n", "", 0)
            ):
                task_id = create_live_codex_model_file_task(
                    project="redletters",
                    title="RedLetters interrupted requirements attempt",
                    goal="Create requirements.txt only",
                    target_paths=["requirements.txt"],
                )
                with self.assertRaises(KeyboardInterrupt):
                    run_next(task_id)
            task_view = show_task(task_id)

        self.assertEqual(task_view["task"]["status"], "failed")
        self.assertEqual(task_view["runs"][0]["status"], "failed")
        self.assertEqual(task_view["runs"][0]["exit_code"], 1)

    def test_gemini_cannot_run_live_codex_scaffold_only(self):
        checks = _redletters_scaffold_preflight(["app/routes.py"], worker="gemini_cli")

        self.assertIn("worker_is_codex", _failed_check_names(checks))
        self.assertIn("project_is_known_writable", _failed_check_names(checks))
        self.assertIn("external_project_write_preflight_authorized", _failed_check_names(checks))

    def test_cli_requires_codex_for_live_codex_scaffold_only(self):
        with mock.patch("app.main.create_live_codex_scaffold_only_task") as create_scaffold:
            exit_code, output, error = _run_cli(
                [
                    "task",
                    "create",
                    "--project",
                    "redletters",
                    "--type",
                    "delegated",
                    "--title",
                    "Bad scaffold",
                    "--goal",
                    "Try scaffold with Gemini",
                    "--worker",
                    "gemini_cli",
                    "--delegation-mode",
                    "live_codex_scaffold_only",
                    "--target-path",
                    "app/routes.py",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(output, "")
        self.assertIn("live_codex_scaffold_only requires --worker codex", error)
        create_scaffold.assert_not_called()


if __name__ == "__main__":
    unittest.main()
