from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from web.app import app


class OperatorWebSubmitTests(unittest.TestCase):
    def test_submit_with_preview_queues_previewed_delegation_mode(self):
        payload = {
            "task": "Build RedLetters MVP",
            "project": "redletters",
            "mode": "deep",
            "delegation_mode": "sequential_pipeline",
            "preview": {
                "project": "redletters",
                "pipeline_raw": "sequential_pipeline",
                "agent1": "claude_code",
                "target_paths": ["README.md"],
            },
        }

        completed = SimpleNamespace(returncode=0, stdout="task-123\n", stderr="")
        with app.test_client() as client, mock.patch("web.app.subprocess.run", return_value=completed) as run:
            response = client.post("/api/submit", json=payload)

        self.assertEqual(response.status_code, 200)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["./scripts/operator", "task", "create"])
        self.assertIn("redletters", command)
        self.assertIn("sequential_pipeline", command)
        self.assertIn("README.md", command)
        self.assertNotIn("do", command)

    def test_submit_rejects_live_preview_without_target_paths(self):
        payload = {
            "task": "Create docs",
            "project": "operator",
            "delegation_mode": "live_codex_docs_only",
            "preview": {
                "project": "operator",
                "pipeline_raw": "live_codex_docs_only",
                "agent1": "codex",
                "target_paths": [],
            },
        }

        with app.test_client() as client, mock.patch("web.app.subprocess.run") as run:
            response = client.post("/api/submit", json=payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn("requires explicit target_paths", response.get_json()["error"])
        run.assert_not_called()

    def test_submit_rejects_policy_file_preview_without_explicit_policy_target(self):
        payload = {
            "task": "Create a handbook mentioning policy",
            "project": "operator",
            "delegation_mode": "live_codex_policy_file_only",
            "preview": {
                "project": "operator",
                "pipeline_raw": "live_codex_policy_file_only",
                "agent1": "codex",
                "target_paths": ["docs/operator-handbook/README.md"],
            },
        }

        with app.test_client() as client, mock.patch("web.app.subprocess.run") as run:
            response = client.post("/api/submit", json=payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn("app/policies.py", response.get_json()["error"])
        run.assert_not_called()

    def test_submit_without_preview_keeps_legacy_do_path(self):
        completed = SimpleNamespace(returncode=0, stdout="task-456\n", stderr="")
        with app.test_client() as client, mock.patch("web.app.subprocess.run", return_value=completed) as run:
            response = client.post("/api/submit", json={"task": "check health", "project": "vps"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            run.call_args.args[0],
            ["./scripts/operator", "do", "check health", "--yes", "--project", "vps"],
        )


if __name__ == "__main__":
    unittest.main()
