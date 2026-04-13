import os
import unittest
from unittest import mock

from app.db import init_db
from app.models import CommandResult
from app.router import create_health_check_task
from app.scheduler import run_next
from app.task_engine import create_task, show_task


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
        self.assertEqual(result["overall_status"], "ok")

    def test_health_check_warning_is_done_not_failed(self):
        runtime_dir = "/tmp/studio116-operator-test-health-warning"
        db_path = f"{runtime_dir}/operator.db"
        if os.path.exists(db_path):
            os.unlink(db_path)
        with mock.patch.dict(
            os.environ,
            {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path},
        ):
            init_db()
            warning_result = CommandResult(
                command="docker ps --format table {{.Names}}",
                stdout="NAMES STATUS PORTS\n",
                stderr="",
                exit_code=0,
            )
            with mock.patch("app.task_engine.inspect_caddy", return_value=[]), mock.patch(
                "app.task_engine.inspect_service", return_value=[]
            ), mock.patch("app.task_engine.inspect_docker_health", return_value=[warning_result]):
                task_id = create_health_check_task()
                result = run_next(task_id)
                task = show_task(task_id)["task"]

        self.assertIs(result["ran"], True)
        self.assertEqual(result["overall_status"], "warning")
        self.assertEqual(task["status"], "done")

    def test_health_check_failed_fails_task(self):
        runtime_dir = "/tmp/studio116-operator-test-health-failed"
        db_path = f"{runtime_dir}/operator.db"
        if os.path.exists(db_path):
            os.unlink(db_path)
        with mock.patch.dict(
            os.environ,
            {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path},
        ):
            init_db()
            failed_result = CommandResult(
                command="systemctl is-active kairoke.service",
                stdout="failed\n",
                stderr="",
                exit_code=3,
            )
            with mock.patch("app.task_engine.inspect_caddy", return_value=[]), mock.patch(
                "app.task_engine.inspect_service", return_value=[failed_result]
            ), mock.patch("app.task_engine.inspect_docker_health", return_value=[]):
                task_id = create_health_check_task()
                result = run_next(task_id)
                task = show_task(task_id)["task"]

        self.assertIs(result["ran"], True)
        self.assertEqual(result["overall_status"], "failed")
        self.assertEqual(task["status"], "failed")

    def test_task_default_requested_by_is_human_friendly(self):
        runtime_dir = "/tmp/studio116-operator-test-identity"
        db_path = f"{runtime_dir}/operator.db"
        if os.path.exists(db_path):
            os.unlink(db_path)
        with mock.patch.dict(
            os.environ,
            {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path},
        ):
            init_db()
            task_id = create_task(project="vps", title="Identity check", goal="Check requested_by")
            task = show_task(task_id)["task"]

        self.assertEqual(task["requested_by"], "Rusty")


if __name__ == "__main__":
    unittest.main()
