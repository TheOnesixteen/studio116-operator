import unittest

from app.models import TASK_STATES
from app.state_manager import can_transition


class StateManagerTests(unittest.TestCase):
    def test_charter_task_states_are_exact(self):
        self.assertEqual(
            TASK_STATES,
            (
                "draft",
                "queued",
                "planning",
                "ready",
                "running",
                "review",
                "blocked",
                "awaiting_approval",
                "done",
                "failed",
                "canceled",
            ),
        )

    def test_phase1_health_lifecycle_path_is_valid(self):
        path = ["draft", "queued", "planning", "ready", "running", "review", "done"]
        self.assertTrue(all(can_transition(left, right) for left, right in zip(path, path[1:])))


if __name__ == "__main__":
    unittest.main()
