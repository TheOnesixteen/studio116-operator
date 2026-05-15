import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

from app.main import main
from app.project_registry import preflight_project_write


def _project(slug: str, *, write_policy: dict | None = None) -> dict:
    project = {
        "slug": slug,
        "name": slug.title(),
        "repo_path": f"/root/Projects/{slug}",
        "stack": ["python"],
        "domains": [],
        "services": [],
        "allowed_agents": ["codex", "claude_code"],
        "deployment_method": "manual",
        "status": "planned",
        "notes": "Test project.",
    }
    if write_policy is not None:
        project["write_policy"] = write_policy
    return project


def _write_policy(*, writable: bool = True, allowed_lane: str | None = "docs_only") -> dict:
    return {
        "writable": writable,
        "allowed_write_agents": ["codex"] if writable else [],
        "allowed_lane": allowed_lane,
        "max_changed_files": 1,
        "allow_file_creation": False,
        "requires_human_approval": True,
        "deployment_allowed": False,
    }


def _write_registry(projects: dict) -> Path:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    with handle:
        yaml.safe_dump({"projects": projects}, handle, sort_keys=False)
    return Path(handle.name)


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class Phase210bExternalWritePreflightTests(unittest.TestCase):
    def test_unknown_project_result(self):
        registry_path = _write_registry({"known": _project("known")})

        result = preflight_project_write("missing", worker="codex", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "unknown_project")
        self.assertFalse(result.authorized)
        self.assertIn("Project slug 'missing' is not in registry/projects.yaml.", result.reasons)

    def test_absent_write_policy_is_known_non_writable(self):
        registry_path = _write_registry({"known": _project("known")})

        result = preflight_project_write("known", worker="codex", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "known_non_writable")
        self.assertFalse(result.authorized)
        self.assertIn("write_policy is absent; absent policy is treated as non-writable.", result.reasons)

    def test_writable_false_is_known_non_writable(self):
        registry_path = _write_registry({"known": _project("known", write_policy=_write_policy(writable=False, allowed_lane=None))})

        result = preflight_project_write("known", worker="codex", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "known_non_writable")
        self.assertFalse(result.authorized)
        self.assertIn("write_policy.writable is false.", result.reasons)

    def test_writable_project_blocks_when_lane_not_authorized(self):
        registry_path = _write_registry({"known": _project("known", write_policy=_write_policy(allowed_lane="tests_only"))})

        result = preflight_project_write("known", worker="codex", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "writable_no_lane_authorized")
        self.assertFalse(result.authorized)
        self.assertIn("Requested lane docs_only does not match write_policy.allowed_lane tests_only.", result.reasons)

    def test_writable_project_blocks_when_worker_not_write_authorized(self):
        registry_path = _write_registry({"known": _project("known", write_policy=_write_policy())})

        result = preflight_project_write("known", worker="claude_code", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "writable_no_lane_authorized")
        self.assertFalse(result.authorized)
        self.assertIn("Requested worker claude_code is not in write_policy.allowed_write_agents.", result.reasons)

    def test_writable_project_authorizes_matching_worker_and_lane(self):
        registry_path = _write_registry({"known": _project("known", write_policy=_write_policy())})

        result = preflight_project_write("known", worker="codex", lane="docs_only", path=registry_path)

        self.assertEqual(result.result_code, "writable_lane_authorized")
        self.assertTrue(result.authorized)
        self.assertIn("Policy allows this worker/lane combination.", result.reasons)

    def test_redletters_cli_authorized_for_docs_only_without_deployment(self):
        with mock.patch("app.main.init_db") as init_db:
            exit_code, output, error = _run_cli(["projects", "preflight-write", "redletters", "--lane", "docs_only", "--worker", "codex"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        init_db.assert_not_called()
        self.assertIn("External write preflight: authorized", output)
        self.assertIn("Project: Red Letters (redletters)", output)
        self.assertIn("Result: writable_lane_authorized", output)
        self.assertIn("- deployment_allowed: false", output)
        self.assertIn("Policy allows this worker/lane combination.", output)
        self.assertIn("Next:", output)
        self.assertIn("No worktree, worker launch, promotion, or deployment occurred.", output)

    def test_operator_cli_authorized_for_docs_only_sanity_check(self):
        with mock.patch("app.main.init_db") as init_db:
            exit_code, output, error = _run_cli(["projects", "preflight-write", "operator", "--lane", "docs_only", "--worker", "codex"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        init_db.assert_not_called()
        self.assertIn("External write preflight: authorized", output)
        self.assertIn("Result: writable_lane_authorized", output)
        self.assertIn("Policy allows this worker/lane combination.", output)
        self.assertIn("This is preflight-only. No worktree, worker launch, promotion, or deployment occurred.", output)


if __name__ == "__main__":
    unittest.main()
