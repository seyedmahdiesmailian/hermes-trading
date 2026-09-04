"""b70 — signal LIMIT orders: parked when entry not reached, filled/expired later."""
import unittest
from datetime import datetime, timedelta, timezone

from engines import paths, signal_pending


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
        paths.signals_dir().mkdir(parents=True, exist_ok=True)
        if paths.pending_state().exists():
            paths.pending_state().unlink()
        signal_pending._last_check = datetime(1970, 1, 1, tzinfo=timezone.utc)

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
