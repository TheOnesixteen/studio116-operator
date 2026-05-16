import tempfile
import unittest
from pathlib import Path
from unittest import mock

from adapters.codex import (
    live_docs_only_command,
    live_model_file_command,
    live_scaffold_only_command,
    run_live_docs_only,
    run_live_model_file,
    run_live_scaffold_only,
)


class CodexAdapterTests(unittest.TestCase):
    def test_live_docs_only_command_is_noninteractive_workspace_write(self):
        packet_path = Path("/tmp/operator-artifacts/worker_packet.json")
        command = live_docs_only_command(worktree_path=Path("/tmp/worktree"), packet_path=packet_path)

        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertIn("--sandbox", command)
        self.assertIn("workspace-write", command)
        self.assertIn("--json", command)
        self.assertIn("--output-last-message", command)
        self.assertIn("-C", command)
        self.assertIn("/tmp/worktree", command)
        self.assertIn(str(packet_path), command[-1])

    def test_run_live_docs_only_passes_worker_packet_on_stdin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            packet_path = tmp_path / "worker_packet.json"
            packet_json = '{"target_paths":["docs/ARCHITECTURE_REVIEW.md"]}'
            packet_path.write_text(packet_json, encoding="utf-8")
            completed = mock.Mock(stdout='{"event":"done"}\n', stderr="", returncode=0)

            with mock.patch("adapters.codex.subprocess.run", return_value=completed) as subprocess_run:
                result = run_live_docs_only(worktree_path=tmp_path / "worktree", packet_path=packet_path, timeout_seconds=12)

        self.assertEqual(result.exit_code, 0)
        subprocess_run.assert_called_once()
        kwargs = subprocess_run.call_args.kwargs
        self.assertEqual(kwargs["input"], packet_json)
        self.assertEqual(kwargs["timeout"], 12)
        self.assertTrue(kwargs["capture_output"])
        self.assertTrue(kwargs["text"])
        self.assertFalse(kwargs["check"])

    def test_run_live_docs_only_reports_missing_packet_as_failure(self):
        result = run_live_docs_only(
            worktree_path=Path("/tmp/worktree"),
            packet_path=Path("/tmp/does-not-exist-worker-packet.json"),
            timeout_seconds=12,
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Unable to read worker packet", result.stderr)

    def test_live_model_file_command_matches_noninteractive_docs_pattern(self):
        packet_path = Path("/tmp/operator-artifacts/worker_packet.json")
        command = live_model_file_command(worktree_path=Path("/tmp/worktree"), packet_path=packet_path)

        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertIn("--sandbox", command)
        self.assertIn("workspace-write", command)
        self.assertIn("--json", command)
        self.assertIn("--output-last-message", command)
        self.assertIn("-C", command)
        self.assertIn("/tmp/worktree", command)
        self.assertIn(str(packet_path), command[-1])

    def test_run_live_model_file_passes_worker_packet_on_stdin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            packet_path = tmp_path / "worker_packet.json"
            packet_json = '{"target_paths":["requirements.txt"]}'
            packet_path.write_text(packet_json, encoding="utf-8")
            completed = mock.Mock(stdout='{"event":"done"}\n', stderr="", returncode=0)

            with mock.patch("adapters.codex.subprocess.run", return_value=completed) as subprocess_run:
                result = run_live_model_file(worktree_path=tmp_path / "worktree", packet_path=packet_path, timeout_seconds=12)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(subprocess_run.call_args.kwargs["input"], packet_json)

    def test_live_scaffold_only_command_is_noninteractive_workspace_write(self):
        packet_path = Path("/tmp/operator-artifacts/worker_packet.json")
        command = live_scaffold_only_command(worktree_path=Path("/tmp/worktree"), packet_path=packet_path)

        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertIn("--sandbox", command)
        self.assertIn("workspace-write", command)
        self.assertIn("--json", command)
        self.assertIn("--output-last-message", command)
        self.assertIn(str(packet_path), command[-1])
        self.assertIn("app/ai_generation.py", command[-1])

    def test_run_live_scaffold_only_passes_worker_packet_on_stdin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            packet_path = tmp_path / "worker_packet.json"
            packet_json = '{"target_paths":["app/routes.py"]}'
            packet_path.write_text(packet_json, encoding="utf-8")
            completed = mock.Mock(stdout='{"event":"done"}\n', stderr="", returncode=0)

            with mock.patch("adapters.codex.subprocess.run", return_value=completed) as subprocess_run:
                result = run_live_scaffold_only(worktree_path=tmp_path / "worktree", packet_path=packet_path, timeout_seconds=12)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(subprocess_run.call_args.kwargs["input"], packet_json)


if __name__ == "__main__":
    unittest.main()
