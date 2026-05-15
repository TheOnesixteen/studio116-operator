import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

from app.main import main
from app.project_registry import load_projects, validate_projects, validate_registry


def _valid_project() -> dict:
    return {
        "slug": "redletters",
        "name": "Red Letters",
        "repo_path": "/root/Projects/redletters.tellthem.ai",
        "stack": ["flask", "sqlite", "caddy"],
        "domains": ["redletters.tellthem.ai"],
        "services": [],
        "allowed_agents": ["codex", "claude_code"],
        "deployment_method": "droplet_systemd",
        "status": "planned",
        "notes": "Faith-tech product. Build not yet started.",
    }


def _non_writable_policy() -> dict:
    return {
        "writable": False,
        "allowed_write_agents": [],
        "allowed_lane": None,
        "max_changed_files": 1,
        "allow_file_creation": False,
        "requires_human_approval": True,
        "deployment_allowed": False,
    }


def _writable_policy() -> dict:
    return {
        "writable": True,
        "allowed_write_agents": ["codex"],
        "allowed_lane": "single_file_code",
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


class Phase210aWritePolicyValidationTests(unittest.TestCase):
    def test_absent_write_policy_validates_as_non_writable(self):
        projects = {"redletters": _valid_project()}

        validation = validate_projects(projects)

        self.assertTrue(validation.ok)
        self.assertEqual(validation.errors, [])

    def test_non_writable_write_policy_validates_cleanly(self):
        project = _valid_project()
        project["write_policy"] = _non_writable_policy()

        validation = validate_projects({"redletters": project})

        self.assertTrue(validation.ok)
        self.assertEqual(validation.errors, [])

    def test_writable_true_requires_complete_policy_shape(self):
        project = _valid_project()
        project["write_policy"] = {"writable": True}

        validation = validate_projects({"redletters": project})

        self.assertFalse(validation.ok)
        self.assertIn("projects.redletters.write_policy: missing required field allowed_write_agents", validation.errors)
        self.assertIn("projects.redletters.write_policy: missing required field deployment_allowed", validation.errors)

    def test_allowed_write_agents_are_closed_and_distinct_from_allowed_agents(self):
        project = _valid_project()
        project["write_policy"] = _writable_policy()
        project["write_policy"]["allowed_write_agents"] = ["n8n", "gemini"]

        validation = validate_projects({"redletters": project})

        self.assertFalse(validation.ok)
        self.assertIn("projects.redletters.write_policy.allowed_write_agents: unknown write agent 'n8n'", validation.errors)
        self.assertIn("projects.redletters.write_policy.allowed_write_agents: unknown write agent 'gemini'", validation.errors)

    def test_gemini_cli_is_not_allowed_write_agent(self):
        project = _valid_project()
        project["allowed_agents"] = ["codex", "claude_code", "gemini_cli"]
        project["write_policy"] = _writable_policy()
        project["write_policy"]["allowed_write_agents"] = ["gemini_cli"]

        validation = validate_projects({"redletters": project})

        self.assertFalse(validation.ok)
        self.assertIn(
            "projects.redletters.write_policy.allowed_write_agents: unknown write agent 'gemini_cli'",
            validation.errors,
        )

    def test_allowed_write_agents_must_be_subset_of_allowed_agents(self):
        project = _valid_project()
        project["allowed_agents"] = ["claude_code"]
        project["write_policy"] = _writable_policy()

        validation = validate_projects({"redletters": project})

        self.assertFalse(validation.ok)
        self.assertIn(
            "projects.redletters.write_policy.allowed_write_agents: write agent 'codex' must also appear in allowed_agents",
            validation.errors,
        )

    def test_allowed_lane_must_be_null_or_known_lane(self):
        project = _valid_project()
        project["write_policy"] = _writable_policy()
        project["write_policy"]["allowed_lane"] = "whole_repo"

        validation = validate_projects({"redletters": project})

        self.assertFalse(validation.ok)
        self.assertIn("projects.redletters.write_policy.allowed_lane: unknown lane 'whole_repo'", validation.errors)

    def test_deployment_allowed_true_fails_in_phase210a(self):
        project = _valid_project()
        project["write_policy"] = _writable_policy()
        project["write_policy"]["deployment_allowed"] = True

        validation = validate_projects({"redletters": project})

        self.assertFalse(validation.ok)
        self.assertIn("projects.redletters.write_policy.deployment_allowed: true is not allowed in Phase 2.10a", validation.errors)

    def test_registry_redletters_allows_gemini_review_without_write_authority(self):
        projects = load_projects()

        redletters = projects["redletters"]

        self.assertEqual(redletters["allowed_agents"], ["codex", "claude_code", "gemini_cli"])
        self.assertNotIn("gemini_cli", redletters["write_policy"]["allowed_write_agents"])
        self.assertEqual(redletters["write_policy"]["allowed_lane"], ["docs_only", "scaffold_only"])
        self.assertTrue(validate_registry().ok)

    def test_projects_show_redletters_prints_write_policy(self):
        with mock.patch("app.main.init_db") as init_db:
            exit_code, output, error = _run_cli(["projects", "show", "redletters"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        init_db.assert_not_called()
        self.assertIn("write_policy:", output)
        self.assertIn("  writable: true", output)
        self.assertIn("  allowed_write_agents: codex, claude_code", output)
        self.assertNotIn("  allowed_write_agents: codex, claude_code, gemini_cli", output)
        self.assertIn("  allowed_lane: docs_only, scaffold_only", output)
        self.assertIn("  deployment_allowed: false", output)

    def test_validate_registry_reports_invalid_write_policy_file(self):
        project = _valid_project()
        project["write_policy"] = _writable_policy()
        project["write_policy"]["allowed_write_agents"] = ["codex"]
        del project["write_policy"]["deployment_allowed"]
        registry_path = _write_registry({"redletters": project})

        validation = validate_registry(registry_path)

        self.assertFalse(validation.ok)
        self.assertIn("projects.redletters.write_policy: missing required field deployment_allowed", validation.errors)
        self.assertIn("projects.redletters.write_policy.deployment_allowed: must be explicit for writable projects", validation.errors)


if __name__ == "__main__":
    unittest.main()
