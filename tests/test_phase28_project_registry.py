import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

from app.main import main
from app.project_registry import load_projects, validate_projects, validate_registry


def _valid_projects() -> dict:
    return {
        "operator": {
            "slug": "operator",
            "name": "Studio 116 Operator",
            "repo_path": "/root/Projects/studio116-operator",
            "stack": ["python", "sqlite", "systemd"],
            "domains": [],
            "services": [],
            "allowed_agents": ["codex", "claude_code"],
            "deployment_method": "manual",
            "status": "active",
            "notes": "The Operator itself. Writable lanes govern all changes.",
        }
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


class Phase28ProjectRegistryTests(unittest.TestCase):
    def test_valid_registry_passes_validation(self):
        validation = validate_projects(_valid_projects())

        self.assertTrue(validation.ok)
        self.assertEqual(validation.errors, [])

    def test_gemini_cli_is_valid_allowed_agent(self):
        projects = _valid_projects()
        projects["operator"]["allowed_agents"] = ["codex", "claude_code", "gemini_cli"]

        validation = validate_projects(projects)

        self.assertTrue(validation.ok)
        self.assertEqual(validation.errors, [])

    def test_slug_must_match_project_key(self):
        projects = _valid_projects()
        projects["operator"]["slug"] = "wrong"

        validation = validate_projects(projects)

        self.assertFalse(validation.ok)
        self.assertIn("projects.operator: slug must match project key", validation.errors)

    def test_unknown_agent_is_rejected(self):
        projects = _valid_projects()
        projects["operator"]["allowed_agents"] = ["codex", "grok"]

        validation = validate_projects(projects)

        self.assertFalse(validation.ok)
        self.assertIn("projects.operator.allowed_agents: unknown agent 'grok'", validation.errors)

    def test_bad_deployment_method_is_rejected(self):
        projects = _valid_projects()
        projects["operator"]["deployment_method"] = "deploy-operator"

        validation = validate_projects(projects)

        self.assertFalse(validation.ok)
        self.assertIn("projects.operator.deployment_method: unknown deployment method 'deploy-operator'", validation.errors)

    def test_missing_required_field_is_rejected(self):
        projects = _valid_projects()
        del projects["operator"]["repo_path"]

        validation = validate_projects(projects)

        self.assertFalse(validation.ok)
        self.assertIn("projects.operator: missing required field repo_path", validation.errors)

    def test_registry_loader_reads_projects_mapping(self):
        registry_path = _write_registry(_valid_projects())

        projects = load_projects(registry_path)

        self.assertEqual(projects["operator"]["name"], "Studio 116 Operator")

    def test_projects_list_is_human_readable(self):
        with mock.patch("app.main.init_db") as init_db:
            exit_code, output, error = _run_cli(["projects", "list"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        init_db.assert_not_called()
        self.assertIn("Projects", output)
        self.assertIn("- operator  Studio 116 Operator", output)
        self.assertIn("deployment: manual", output)

    def test_projects_show_slug_is_human_readable(self):
        with mock.patch("app.main.init_db") as init_db:
            exit_code, output, error = _run_cli(["projects", "show", "operator"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        init_db.assert_not_called()
        self.assertIn("Studio 116 Operator (operator)", output)
        self.assertIn("repo_path: /root/Projects/studio116-operator", output)
        self.assertIn("deployment_method: manual", output)

    def test_projects_validate_reports_success(self):
        with mock.patch("app.main.init_db") as init_db:
            exit_code, output, error = _run_cli(["projects", "validate"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        init_db.assert_not_called()
        self.assertEqual(output.strip(), "Project registry is valid.")

    def test_validate_registry_reports_invalid_file(self):
        projects = _valid_projects()
        projects["operator"]["domains"] = ["https://operator.example/path"]
        registry_path = _write_registry(projects)

        validation = validate_registry(registry_path)

        self.assertFalse(validation.ok)
        self.assertIn(
            "projects.operator.domains: 'https://operator.example/path' must be a hostname only",
            validation.errors,
        )


if __name__ == "__main__":
    unittest.main()
