"""Telegram offset ownership tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic  # noqa: E402
from engines import paths
import engines.signal_listener as listener  # noqa: E402


class SignalPollLockTest(unittest.TestCase):
    def setUp(self):
        self.root = hermetic.use_temp_data_root()
        self.original_api = listener._telegram_api

    def tearDown(self):
        listener._telegram_api = self.original_api
        hermetic.release()

    def test_poll_persists_offset_under_lock(self):
        seen_offsets = []

        def api(method, params=None):
            seen_offsets.append(params["offset"])
            return {"ok": True, "result": [{
                "update_id": 41,
                "message": {
                    "chat": {"id": "-100test", "title": "signals"},
                    "from": {"first_name": "tester"},
                    "text": "not a signal",
                    "date": 1,
                },
            }]}

        listener._telegram_api = api
        messages = listener.fetch_new_messages()
        self.assertEqual(seen_offsets, ["1"])
        self.assertEqual(messages[0]["update_id"], 41)
        self.assertEqual(
            paths.read_json_safe(paths.listener_state(), {})["last_update_id"], 41)

    def test_timeout_skips_without_polling(self):
        class BusyLock:
            def __enter__(self):
                raise TimeoutError("busy")

            def __exit__(self, *args):
                return False

        original_lock = listener._state_lock
        listener._state_lock = lambda *args, **kwargs: BusyLock()
        listener._telegram_api = lambda *args, **kwargs: self.fail("must not poll")
        try:
            self.assertEqual(listener.fetch_new_messages(), [])
        finally:
            listener._state_lock = original_lock


if __name__ == "__main__":
    unittest.main()
