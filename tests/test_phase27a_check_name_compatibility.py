import unittest

from app.policies import (
    validate_live_codex_model_file_paths,
    validate_live_codex_policy_file_paths,
)


def _check_by_name(checks: list[dict], name: str) -> dict:
    return next(check for check in checks if check["name"] == name)


class Phase27aCheckNameCompatibilityTests(unittest.TestCase):
    def test_policy_file_path_check_emits_legacy_and_target_names(self):
        invalid_checks = validate_live_codex_policy_file_paths(["app/main.py"])
        invalid_legacy_check = _check_by_name(invalid_checks, "paths_are_policy_file")
        invalid_target_check = _check_by_name(invalid_checks, "paths_are_policy_file_target")

        self.assertFalse(invalid_legacy_check["passed"])
        self.assertFalse(invalid_target_check["passed"])

        valid_checks = validate_live_codex_policy_file_paths(["app/policies.py"])
        valid_legacy_check = _check_by_name(valid_checks, "paths_are_policy_file")
        valid_target_check = _check_by_name(valid_checks, "paths_are_policy_file_target")

        self.assertTrue(valid_legacy_check["passed"])
        self.assertTrue(valid_target_check["passed"])

    def test_model_file_path_check_uses_target_name(self):
        checks = validate_live_codex_model_file_paths(["app/main.py"])
        target_check = _check_by_name(checks, "paths_are_model_file_target")

        self.assertFalse(target_check["passed"])


if __name__ == "__main__":
    unittest.main()
