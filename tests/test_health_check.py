import os
import unittest
from unittest import mock

from app.db import init_db
from app.router import create_health_check_task
from app.scheduler import run_next
from app.task_engine import show_task


class HealthCheckTests(unittest.TestCase):
    def test_health_check_uses_scheduler_lifecycle(self):
        runtime_dir = "/tmp/studio116-operator-test-health"
        db_path = f"{runtime_dir}/operator.db"
        if os.path.exists(db_path):
            os.unlink(db_path)
        with mock.patch.dict(
            os.environ,
            {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path},
        ):
            init_db()

            with mock.patch("app.task_engine.inspect_caddy", return_value=[]), mock.patch(
                "app.task_engine.inspect_service", return_value=[]
            ), mock.patch("app.task_engine.inspect_docker_health", return_value=[]):
                task_id = create_health_check_task()
                result = run_next(task_id)
                task = show_task(task_id)["task"]

        self.assertIs(result["ran"], True)
        self.assertEqual(task["status"], "done")


if __name__ == "__main__":
    unittest.main()
