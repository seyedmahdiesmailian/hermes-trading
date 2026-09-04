"""b70 — signal LIMIT orders: parked when entry not reached, filled/expired later."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hermetic
from engines import signal_pending


class FakeBridge:
    def __init__(self):
        self.placed = []
        self.cancelled = []
        self.live_ids = set()
        self.deals = []

    def send_pending(self, side, lot, symbol="XAUUSD", price=None, sl=None, tp=None):
        self.placed.append({"side": side, "price": price, "sl": sl, "tp": tp, "lot": lot})
        self.live_ids.add(9001)
        return {"ok": True, "ticket": 9001}

    def get_orders(self):
        return {"ok": True, "data": [{"ticket": t} for t in sorted(self.live_ids)]}

    def cancel_order(self, ticket):
        self.cancelled.append(ticket)
        self.live_ids.discard(ticket)
        return {"ok": True}

    def get_history_deals(self, symbol="XAUUSD", days=2):
        return {"ok": True, "data": self.deals}


def _cmd(side="BUY", entry=4472.0):
    return {"side": side, "entry": entry, "sl": entry - 10, "tp": entry + 20,
            "lot": 0.02, "symbol": "XAUUSD"}


class PendingTests(unittest.TestCase):
    def setUp(self):
        # b71 FIX: this suite used to write straight into PRODUCTION state —
        # paths.pending_state() resolved to the live data/signals/ tree, so a
        # test run parked a fake ticket 9001 @ 4472.0 that the live daemon
        # then reconciled against the real broker, found missing, and fired
        # "⚠️ LIMIT از لیست بروکر حذف شد..." at the user. Tests must never
        # touch live state. Use the STANDARD hermetic seam (env var), not
        # paths.set_data_root(): the clean-checkout verifier exports
        # HERMES_DATA_ROOT, which OVERRIDES set_data_root — with the override
        # alone every test in this file shared one state file and bled into
        # the next (pending_cap leftovers made place fail; stale tickets
        # reported 'vanished' instead of 'ttl_cancel').
        hermetic.use_temp_data_root()
        signal_pending._last_check = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def tearDown(self):
        hermetic.release()

    def _state(self):
        return signal_pending.load_pending()

    def test_place_parks_and_dedupes(self):
        b = FakeBridge()
        r = signal_pending.place_signal_limit(b, _cmd())
        self.assertTrue(r["ok"])
        self.assertEqual(b.placed[0]["side"], "BUY")
        self.assertEqual(b.placed[0]["price"], 4472.0)
        self.assertEqual(len(self._state()), 1)
        r2 = signal_pending.place_signal_limit(b, _cmd())
        self.assertFalse(r2["ok"])
        self.assertEqual(r2["error"], "duplicate_pending")
        self.assertEqual(len(b.placed), 1)

    def test_invalid_command_refused(self):
        b = FakeBridge()
        bad = _cmd(); bad["tp"] = 0
        r = signal_pending.place_signal_limit(b, bad)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "invalid_command")
        self.assertEqual(b.placed, [])

    def test_pending_cap(self):
        b = FakeBridge()
        for i in range(signal_pending.pending_max()):
            self.assertTrue(signal_pending.place_signal_limit(b, _cmd(entry=4400 + i))["ok"])
        r = signal_pending.place_signal_limit(b, _cmd(entry=4500))
        self.assertFalse(r["ok"])
        self.assertTrue(r["error"].startswith("pending_cap"))

    def test_fill_detected(self):
        b = FakeBridge()
        signal_pending.place_signal_limit(b, _cmd())
        b.live_ids = set()   # filled orders leave the active-orders list
        b.deals = [{"order": 9001, "entry": 0, "price": 4472.0}]
        events = signal_pending.watch_pending(b)
        self.assertEqual(events, [{"event": "filled", "ticket": 9001}])
        self.assertEqual(self._state(), [])

    def test_ttl_expiry_cancels(self):
        b = FakeBridge()
        signal_pending.place_signal_limit(b, _cmd())
        items = self._state()
        items[0]["placed_at"] = (datetime.now(timezone.utc) - timedelta(minutes=600)).isoformat()
        signal_pending.save_pending(items)
        events = signal_pending.watch_pending(b)
        self.assertEqual(events[0]["event"], "ttl_cancel")
        self.assertIn(9001, b.cancelled)
        self.assertEqual(self._state(), [])

    def test_kill_switch_cancels_all(self):
        b = FakeBridge()
        signal_pending.place_signal_limit(b, _cmd())
        events = signal_pending.watch_pending(b, kill_halted=True)
        self.assertEqual(events[0]["event"], "cancel_all")
        self.assertIn(9001, b.cancelled)
        self.assertEqual(self._state(), [])

    def test_market_closed_cancels_all(self):
        b = FakeBridge()
        signal_pending.place_signal_limit(b, _cmd())
        events = signal_pending.watch_pending(b, market_open=False)
        self.assertEqual(events[0]["reason"], "market_closed")
        self.assertEqual(self._state(), [])

    def test_vanished_not_mistaken_for_fill(self):
        b = FakeBridge()
        signal_pending.place_signal_limit(b, _cmd())
        b.live_ids = set()   # broker: order gone
        b.deals = [{"order": 9001, "entry": 1, "price": 4472.0}]  # OUT deal only
        events = signal_pending.watch_pending(b)
        self.assertEqual(events[0]["event"], "vanished")


if __name__ == "__main__":
    unittest.main()
