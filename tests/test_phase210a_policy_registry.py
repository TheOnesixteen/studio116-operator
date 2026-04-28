import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

from app.main import main
from app.policies import validate_policy_registry


def _current_policy_data() -> dict:
    return yaml.safe_load(Path("registry/policies.yaml").read_text(encoding="utf-8"))


def _write_policy_registry(data) -> Path:
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    with handle:
        yaml.safe_dump(data, handle, sort_keys=False)
    return Path(handle.name)


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class Phase210aPolicyRegistryTests(unittest.TestCase):
    def test_current_policy_registry_passes_validation(self):
        validation = validate_policy_registry()

        self.assertTrue(validation.ok)
        self.assertEqual(validation.errors, [])

    def test_policy_registry_root_must_be_mapping(self):
        registry_path = _write_policy_registry(["not", "a", "mapping"])

        validation = validate_policy_registry(registry_path)

        self.assertFalse(validation.ok)
        self.assertIn("policy registry root must be a mapping", validation.errors)

    def test_missing_required_section_is_rejected(self):
        policies = _current_policy_data()
        del policies["live_codex_policy_file_allowed_targets"]
        registry_path = _write_policy_registry(policies)

        validation = validate_policy_registry(registry_path)

        self.assertFalse(validation.ok)
        self.assertIn(
            "policies.live_codex_policy_file_allowed_targets: missing required section",
            validation.errors,
        )

    def test_policy_list_sections_require_nonempty_string_entries(self):
        policies = _current_policy_data()
        policies["allowed_without_approval"] = ["inspect_files", "", 123, "inspect_files"]
        registry_path = _write_policy_registry(policies)

        validation = validate_policy_registry(registry_path)

        self.assertFalse(validation.ok)
        self.assertIn("policies.allowed_without_approval: entries must be non-empty strings", validation.errors)
        self.assertIn("policies.allowed_without_approval: duplicate entry 'inspect_files'", validation.errors)

    def test_live_codex_targets_must_remain_phase_approved(self):
        policies = _current_policy_data()
        policies["live_codex_policy_file_allowed_targets"] = ["app/policies.py", "app/router.py"]
        registry_path = _write_policy_registry(policies)

        validation = validate_policy_registry(registry_path)

        self.assertFalse(validation.ok)
        self.assertIn(
            "policies.live_codex_policy_file_allowed_targets: 'app/router.py' is not an approved Phase 2 target",
            validation.errors,
        )

    def test_lock_policy_requires_sqlite_scheduler_owned_locks(self):
        policies = _current_policy_data()
        policies["lock_policy"]["authority"] = "file"
        policies["lock_policy"]["scheduler_owns_locks"] = False
        registry_path = _write_policy_registry(policies)

        validation = validate_policy_registry(registry_path)

        self.assertFalse(validation.ok)
        self.assertIn("policies.lock_policy.authority: must be 'sqlite'", validation.errors)
        self.assertIn("policies.lock_policy.scheduler_owns_locks: must be true", validation.errors)

    def test_policies_validate_reports_success_without_database_init(self):
        with mock.patch("app.main.init_db") as init_db:
            exit_code, output, error = _run_cli(["policies", "validate"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        init_db.assert_not_called()
        self.assertEqual(output.strip(), "Policy registry is valid.")


if __name__ == "__main__":
    unittest.main()
