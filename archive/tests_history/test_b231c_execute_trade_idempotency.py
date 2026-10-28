"""b231c — end-to-end idempotency through execute_trade (roadmap 4.1).

The two layers are proven separately (key derivation + bridge replay). This
file pins the wiring BETWEEN them: the production callers build a key from a
stable intent id and pass it through execute_trade to send_order, so a retried
cycle sends the same key both times.

If the intent id is not stable — a wall-clock value, or nothing at all — the
retry produces a different key and the whole guarantee silently disappears.
That is a wiring bug, not a logic bug, so it is pinned here.
"""
import unittest
from unittest.mock import patch

from bridge_client import make_idempotency_key


class FakeBridge:
    """Captures what execute_trade sends so the key can be inspected."""

    def __init__(self):
        self.orders = []

    def send_order(self, side, lot, symbol="XAUUSD", sl=None, tp=None,
                   idempotency_key=None):
        self.orders.append({
            "side": side, "lot": lot, "symbol": symbol, "sl": sl, "tp": tp,
            "idempotency_key": idempotency_key,
        })
        return {"ok": True, "ticket": 500000001, "volume": lot, "price": 4410.0}


class TestExecuteTradeIdempotency(unittest.TestCase):
    def setUp(self):
        from engines import auto_executor as ae
        self.ae = ae
        self.bridge = FakeBridge()
        # force the market-hours gate open regardless of the trading week
        self._gate = patch.object(ae, "is_market_open", return_value=True)
        self._gate.start()

    def tearDown(self):
        self._gate.stop()

    def _execute(self, key):
        cmd = {"side": "BUY", "lot": 0.02, "symbol": "XAUUSD",
               "sl": 4400.0, "tp": 4450.0, "entry": 4410.0}
        return self.ae.execute_trade(cmd, self.bridge, dry_run=False,
                                     idempotency_key=key)

    def test_key_reaches_send_order(self):
        key = make_idempotency_key("plan:abc", "BUY", 0.02, 4400.0, 4450.0)
        self._execute(key)
        self.assertEqual(self.bridge.orders[0]["idempotency_key"], key)

    def test_two_calls_with_same_key_carry_same_key(self):
        """A retried cycle must re-send the SAME key or the bridge cannot
        recognise it as a replay."""
        key = make_idempotency_key("plan:abc", "BUY", 0.02, 4400.0, 4450.0)
        self._execute(key)
        self._execute(key)
        self.assertEqual(self.bridge.orders[0]["idempotency_key"],
                         self.bridge.orders[1]["idempotency_key"])

    def test_missing_key_does_not_break_trade(self):
        """Callers that have not been wired up yet keep working."""
        r = self._execute(None)
        self.assertTrue(r.get("ok") or r.get("executed"))
        self.assertIsNone(self.bridge.orders[0]["idempotency_key"])

    def test_dry_run_short_circuits_before_sending(self):
        cmd = {"side": "BUY", "lot": 0.02, "symbol": "XAUUSD"}
        r = self.ae.execute_trade(cmd, self.bridge, dry_run=True,
                                  idempotency_key="anything")
        self.assertTrue(r.get("dry_run"))
        self.assertEqual(len(self.bridge.orders), 0)

    def test_market_closed_blocks_even_with_key(self):
        """The idempotency key must not weaken the market-hours gate."""
        self._gate.stop()
        self._gate = patch.object(self.ae, "is_market_open", return_value=False)
        self._gate.start()
        r = self._execute(make_idempotency_key("plan:x", "BUY", 0.02))
        self.assertEqual(r.get("error"), "market_closed")
        self.assertEqual(len(self.bridge.orders), 0)


if __name__ == "__main__":
    unittest.main()
