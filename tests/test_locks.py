import os
import unittest
from unittest import mock

from app.db import init_db
from app.locks import acquire_lock, release_lock


class LockTests(unittest.TestCase):
    def test_only_one_active_sqlite_lock(self):
        runtime_dir = "/tmp/studio116-operator-test-locks"
        db_path = f"{runtime_dir}/operator.db"
        if os.path.exists(db_path):
            os.unlink(db_path)
        with mock.patch.dict(
            os.environ,
            {"OPERATOR_RUNTIME_DIR": runtime_dir, "OPERATOR_DB_PATH": db_path},
        ):
            init_db()

            lock_id = acquire_lock(lock_type="scheduler", resource_key="run_next")
            with self.assertRaises(RuntimeError):
                acquire_lock(lock_type="scheduler", resource_key="run_next")

            release_lock(lock_id)
            second_lock_id = acquire_lock(lock_type="scheduler", resource_key="run_next")
            release_lock(second_lock_id)


if __name__ == "__main__":
    unittest.main()
