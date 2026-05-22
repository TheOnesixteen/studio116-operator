import unittest
import json
import subprocess

from app.intake.normalizer import normalize_task
from app.intake.risk_scorer import score_risk
from app.policies import load_policy_registry
from app.project_registry import load_projects


HANDBOOK_PROMPT = """Create the Operator Operational Handbook files under docs/operator-handbook/.

Create:
- README.md
- architecture.md
- project-registry-and-policy.md
- review-and-promotion.md

Rules:
- Docs-only.
- Do not change app code.
- Explain policy, architecture, registry, review, and services.
"""


class HandbookRoutingTests(unittest.TestCase):
    def _normalize(self, prompt: str):
        projects = load_projects()
        policies = load_policy_registry()
        risk = score_risk(prompt, "operator", {"projects": projects})
        return normalize_task(
            prompt,
            "operator",
            "/root/Projects/studio116-operator",
            projects,
            policies,
            risk_score=risk,
            normalizer_override="local",
        )

    def test_handbook_docs_target_routes_docs_only_not_policy_file(self):
        task = self._normalize(HANDBOOK_PROMPT)

        self.assertEqual(task.delegation_mode, "live_codex_docs_only")
        self.assertNotEqual(task.delegation_mode, "live_codex_policy_file_only")
        self.assertIn("docs/operator-handbook/README.md", task.target_paths)
        self.assertIn("docs/operator-handbook/project-registry-and-policy.md", task.target_paths)

    def test_policy_mentions_inside_manual_still_route_docs_only(self):
        task = self._normalize(
            "Write documentation manual files under docs/operator-handbook/ about policy, services, and review.\n"
            "- policy-and-services.md"
        )

        self.assertEqual(task.delegation_mode, "live_codex_docs_only")
        self.assertEqual(task.target_paths, ["docs/operator-handbook/policy-and-services.md"])

    def test_preview_worker_preserves_explicit_markdown_target(self):
        payload = {
            "task": "Write a project onboarding page that mentions policy",
            "project": "operator",
            "mode": "deep",
            "target_paths": ["docs/operator-handbook/how-to-add-a-project.md"],
            "project_root": "/root/Projects/studio116-operator",
        }

        result = subprocess.run(
            ["python3", "web/preview_worker.py"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["ok"])
        self.assertEqual(data["preview"]["pipeline_raw"], "live_codex_docs_only")
        self.assertEqual(data["preview"]["target_paths"], ["docs/operator-handbook/how-to-add-a-project.md"])


if __name__ == "__main__":
    unittest.main()
