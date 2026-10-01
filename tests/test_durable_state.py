"""Regression tests for durable state I/O (b25, 2026-08-30 audit).

Two failure modes these guard against, both of which were live risks:

1. NON-ATOMIC WRITES — a crash mid-write_text() left a truncated JSON file.
2. CRASHING READERS — storage.load_current_plan / load_runtime_state /
   load_performance_state called json.loads() with no try/except, so one
   half-written file killed every subsequent trading cycle silently.
"""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic  # noqa: E402  (shared temp-root switch)
from engines import paths


class TempRootCase(unittest.TestCase):
    """Every state write in these tests lands in a throwaway directory."""

    def setUp(self):
        self.root = hermetic.use_temp_data_root()

    def tearDown(self):
        hermetic.release()


class AtomicWriteTest(TempRootCase):
    def test_roundtrip_and_no_tmp_leftover(self):
        f = paths.plan_dir() / "atomic_probe.json"
        paths.write_json_atomic(f, {"a": 1, "b": [1, 2]}, indent=2)
        self.assertEqual(json.loads(f.read_text()), {"a": 1, "b": [1, 2]})
        self.assertFalse((f.with_name(f.name + ".tmp")).exists(),
                         "temp file must be renamed away, not left behind")

    def test_serializes_datetimes(self):
        from datetime import datetime, timezone
        f = paths.plan_dir() / "atomic_dt.json"
        paths.write_json_atomic(f, {"t": datetime.now(timezone.utc)})
        self.assertIn("2026", json.loads(f.read_text())["t"])

    def test_overwrite_is_complete(self):
        f = paths.plan_dir() / "atomic_over.json"
        paths.write_json_atomic(f, {"big": "x" * 10000})
        paths.write_json_atomic(f, {"small": 1})
        self.assertEqual(json.loads(f.read_text()), {"small": 1})

    def test_concurrent_writers_do_not_share_a_temp_file(self):
        """Master/signal/watchdog state writes may overlap on a live box.

        Last-writer-wins is acceptable for this integrity primitive; an
        exception, truncated JSON, or leaked temporary file is not.
        """
        f = paths.plan_dir() / "atomic_concurrent.json"
        barrier = threading.Barrier(12)
        errors = []

        def write(i):
            try:
                barrier.wait(timeout=5)
                paths.write_json_atomic(f, {"writer": i, "payload": "x" * 1000})
            except Exception as exc:  # captured so the test reports the race
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(errors, [])
        self.assertEqual(json.loads(f.read_text())["payload"], "x" * 1000)
        self.assertEqual(list(paths.plan_dir().glob(".atomic_concurrent.json.*.tmp")), [])


class CorruptReadTest(TempRootCase):
    def test_read_json_safe_quarantines_and_defaults(self):
        f = paths.plan_dir() / "corrupt_probe.json"
        f.write_text('{"truncated": tr')          # half-written JSON
        got = paths.read_json_safe(f, {"fallback": True}, label="probe")
        self.assertEqual(got, {"fallback": True})
        self.assertFalse(f.exists(), "corrupt file must be moved aside")
        quarantined = list(paths.plan_dir().glob("corrupt_probe.json.corrupt.*"))
        self.assertEqual(len(quarantined), 1)

    def test_missing_file_returns_default(self):
        f = paths.plan_dir() / "never_written.json"
        self.assertEqual(paths.read_json_safe(f, {}), {})


class StorageSurvivesCorruptionTest(TempRootCase):
    """The three critical readers must degrade, never raise."""

    def test_loaders_return_defaults_on_garbage(self):
        from engines import storage
        d = paths.plan_dir()
        (d / "current_plan.json").write_text("{{{not json")
        (d / "runtime_state.json").write_text("nope")
        (d / "performance_state.json").write_text("")
        self.assertIsNone(storage.load_current_plan(d))
        self.assertEqual(storage.load_runtime_state(d), {})
        self.assertEqual(storage.load_performance_state(d), {})

    def test_save_plan_survives_corrupt_predecessor(self):
        """A corrupt current_plan must not block the next plan save, and the
        corrupt content must not be archived as if it were a real plan."""
        from engines import storage
        d = paths.plan_dir()
        (d / "current_plan.json").write_text('{"pla')
        before = len(list((d / "plan_history").glob("*.json")))
        storage.save_current_plan(d, {"plan_id": "good", "bias": "bullish"})
        plan = storage.load_current_plan(d)
        self.assertEqual(plan["plan_id"], "good")
        after = len(list((d / "plan_history").glob("*.json")))
        self.assertEqual(after, before, "corrupt plan must not be archived")


class KillSwitchFailClosedTest(TempRootCase):
    """Corrupt kill-switch state must NOT silently disarm protection."""

    def test_defaults_are_not_halted(self):
        # Document the deliberate choice: kill_switch._load_state() falls back
        # to halted=False on corruption. Atomic writes (b25) make the
        # half-written scenario ~impossible; a false halt that never clears
        # would be worse. If anyone changes the default, this test must be
        # revisited with that trade-off in mind.
        paths.kill_switch_state().parent.mkdir(parents=True, exist_ok=True)
        paths.kill_switch_state().write_text("garbage{{{")
        from engines import kill_switch
        st = kill_switch._load_state()
        self.assertFalse(st["halted"])
        self.assertEqual(st["consecutive_losses"], 0)


if __name__ == "__main__":
    unittest.main()
