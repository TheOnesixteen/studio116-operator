import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.git_tools import git_changed_files, git_diff


class GitToolsTests(unittest.TestCase):
    def test_diff_and_changed_files_include_untracked_files_without_staging(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "initial"], check=True)

            (repo / "README.md").write_text("hello\nupdated\n", encoding="utf-8")
            (repo / "docs").mkdir()
            (repo / "docs" / "PLAN.md").write_text("# Plan\n", encoding="utf-8")

            changed = git_changed_files(worktree_path=repo)
            diff = git_diff(worktree_path=repo)
            status = subprocess.run(["git", "-C", str(repo), "status", "--short"], capture_output=True, text=True, check=True)

        self.assertEqual(changed.exit_code, 0)
        self.assertEqual(changed.stdout.splitlines(), ["README.md", "docs/PLAN.md"])
        self.assertEqual(diff.exit_code, 0)
        self.assertIn("diff --git a/README.md b/README.md", diff.stdout)
        self.assertIn("diff --git a/docs/PLAN.md b/docs/PLAN.md", diff.stdout)
        self.assertIn("?? docs/", status.stdout)


if __name__ == "__main__":
    unittest.main()
