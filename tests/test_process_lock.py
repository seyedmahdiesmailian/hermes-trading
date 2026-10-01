"""Tests for the cross-daemon state lock."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hermetic  # noqa: E402
from engines import paths
from engines.process_lock import exclusive


class ProcessLockTest(unittest.TestCase):
    def setUp(self):
        self.root = hermetic.use_temp_data_root()

    def tearDown(self):
        hermetic.release()

    def test_creates_lock_below_active_data_root(self):
        with exclusive("unit_state") as lock_path:
            self.assertEqual(lock_path, paths.data_dir() / "locks" / "unit_state.lock")
            self.assertTrue(lock_path.exists())

    def test_does_not_yield_when_already_held(self):
        with exclusive("unit_state"):
            with self.assertRaises(TimeoutError):
                with exclusive("unit_state", timeout=0.05):
                    self.fail("an overlapping writer must not enter")

    def test_rejects_path_traversal_names(self):
        with self.assertRaises(ValueError):
            with exclusive("../performance_state"):
                pass


if __name__ == "__main__":
    unittest.main()
