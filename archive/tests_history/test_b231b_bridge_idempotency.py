"""b231b — bridge-side order idempotency (roadmap 4.1).

Companion to tests/test_b231_order_idempotency.py. That file proves the client
puts the right key on the wire; THIS one proves the server does something
correct with it:

  * a first order is sent to the broker (no phantom replay).
  * a retried copy of the same intent is answered from the ledger and the
    broker is NOT asked again — this is the exact bug: a lost reply followed by
    a retry used to open a second position.
  * the replayed answer is the FIRST answer (same ticket), not a fresh one.
  * keyless orders still trade, so a not-yet-redeployed bridge keeps working.
  * a corrupt ledger cannot stop trading (fail-safe direction).

The bridge module imports MetaTrader5, which does not exist on Linux. It is
injected into sys.modules before the import so the real code path is executed
and only the broker boundary is stubbed — never the idempotency logic itself.
"""
import json
import os
import sys
import tempfile
import types
import unittest


def _load_bridge_module(ledger_path):
    """Import the canonical bridge with MetaTrader5 stubbed.

    Only the broker boundary is faked (order_send / symbol_info_tick). The
    ledger read/write helpers and the /api/order route logic are the REAL
    production code under test.
    """
    mt5 = types.ModuleType("MetaTrader5")
    # A bridge import is executed, so every module-level constant the source
    # references must exist. Rather than hand-maintain a list (which drifts the
    # moment a route is added), anything not explicitly stubbed below falls back
    # to a distinct sentinel value — enough for import and route dispatch, while
    # the behaviour under test is driven by the explicit stubs.
    _SEEN = {}

    class _Any:
        """Returns a unique int for any attribute name (as MT5 constants are)."""

        def __getattr__(self, name):
            if name not in _SEEN:
                _SEEN[name] = 70000 + len(_SEEN)
            return _SEEN[name]

    _ANY = _Any()
    for _name in ("TRADE_RETCODE_DONE", "TRADE_ACTION_DEAL",
                  "TRADE_ACTION_PENDING", "TRADE_ACTION_REMOVE",
                  "TRADE_ACTION_SLTP", "ORDER_FILLING_IOC", "ORDER_FILLING_FOK",
                  "ORDER_TIME_GTC", "ORDER_TIME_SPECIFIED",
                  "ORDER_TYPE_BUY", "ORDER_TYPE_SELL",
                  "ORDER_TYPE_BUY_LIMIT", "ORDER_TYPE_SELL_LIMIT",
                  "ORDER_TYPE_BUY_STOP", "ORDER_TYPE_SELL_STOP",
                  "TIMEFRAME_M1", "TIMEFRAME_M5", "TIMEFRAME_M15",
                  "TIMEFRAME_M30", "TIMEFRAME_H1", "TIMEFRAME_H4",
                  "TIMEFRAME_D1", "TIMEFRAME_W1"):
        mt5.__setattr__(_name, getattr(_ANY, _name))
    mt5.TRADE_RETCODE_DONE = 10009
    mt5.TRADE_ACTION_DEAL = 1
    mt5.TRADE_ACTION_PENDING = 5
    mt5.TRADE_ACTION_REMOVE = 3
    mt5.TRADE_ACTION_SLTP = 6
    mt5.PENDING_TYPES = None
    mt5.POSITION_TYPE_BUY = 0
    mt5.POSITION_TYPE_SELL = 1
    mt5.DEAL_ENTRY_IN = 1
    mt5.DEAL_ENTRY_OUT = 0

    class _Result:
        def __init__(self, retcode=10009, order=500000000, volume=0.02,
                     price=4410.0, comment=""):
            self.retcode = retcode
            self.order = order
            self.volume = volume
            self.price = price
            self.comment = comment

    class _Tick:
        ask = 4410.5
        bid = 4410.0
        last = 4410.2
        volume = 0

    # Tracks how many times the broker was actually asked for an order.
    state = {"order_send_calls": 0, "next_ticket": 500000000}

    def order_send(request_dict):
        state["order_send_calls"] += 1
        state["next_ticket"] += 1
        return _Result(order=state["next_ticket"], volume=request_dict["volume"])

    def symbol_info_tick(symbol):
        return _Tick()

    def symbol_select(symbol, flag=True):
        return True

    def initialize(*a, **k):
        return True

    def shutdown():
        return None

    def positions_get(*a, **k):
        return ()

    def orders_get(*a, **k):
        return ()

    def deals_get(*a, **k):
        return ()

    def account_info(*a, **k):
        return None

    def last_error():
        return (0, "no error")

    mt5.order_send = order_send
    mt5.symbol_info_tick = symbol_info_tick
    mt5.symbol_select = symbol_select
    mt5.initialize = initialize
    mt5.shutdown = shutdown
    mt5.positions_get = positions_get
    mt5.orders_get = orders_get
    mt5.deals_get = deals_get
    mt5.account_info = account_info
    mt5.last_error = last_error

    sys.modules["MetaTrader5"] = mt5

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    os.environ["HERMES_IDEM_LEDGER"] = ledger_path
    os.environ["HERMES_BRIDGE_TOKEN"] = "test-token"
    # The bridge opens a logging FileHandler at import time; point it at the
    # temp dir so the Linux test run does not try to write under C:/.
    os.environ["HERMES_BRIDGE_LOG"] = os.path.join(
        os.path.dirname(ledger_path), "bridge_test.log")

    import importlib
    import mt5_http_server_v2 as bridge
    importlib.reload(bridge)
    return bridge, state


class TestBridgeIdempotency(unittest.TestCase):
    """The replay logic in the canonical bridge server."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="idem_bridge_")
        cls.ledger = os.path.join(cls._tmpdir, "idem_ledger.json")
        cls.bridge, cls.state = _load_bridge_module(cls.ledger)
        cls.app = cls.bridge.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def _post(self, payload):
        return self.client.post("/api/order", json=payload,
                                headers={"Authorization": "Bearer test-token"})

    def test_first_order_reaches_broker(self):
        self.state["order_send_calls"] = 0
        r = self._post({"type": "buy", "volume": 0.02, "symbol": "XAUUSD",
                        "sl": 4400.0, "tp": 4450.0,
                        "comment": "hms" + "a" * 10})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.state["order_send_calls"], 1)

    def test_retry_of_same_key_does_not_trade_again(self):
        """The bug: a lost reply + retry opened a SECOND position."""
        self.state["order_send_calls"] = 0
        payload = {"type": "buy", "volume": 0.02, "symbol": "XAUUSD",
                   "sl": 4400.0, "tp": 4450.0,
                   "comment": "hms" + "b" * 10}
        first = self._post(payload)
        first_ticket = first.get_json()["ticket"]

        # reply is lost on the LAN; daemon retries the same intent
        second = self._post(payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        # ONE order to the broker, not two
        self.assertEqual(self.state["order_send_calls"], 1)
        # the retry got the SAME ticket, not a fresh one
        self.assertEqual(second.get_json()["ticket"], first_ticket)

    def test_replay_answer_carries_same_fields(self):
        payload = {"type": "sell", "volume": 0.03, "symbol": "XAUUSD",
                   "sl": 4450.0, "tp": 4400.0,
                   "comment": "hms" + "c" * 10}
        first = self._post(payload).get_json()
        second = self._post(payload).get_json()
        self.assertEqual(first, second)

    def test_keyless_order_still_trades(self):
        """Back-compat: the deployed-but-not-redeployed bridge keeps trading."""
        self.state["order_send_calls"] = 0
        r = self._post({"type": "buy", "volume": 0.01, "symbol": "XAUUSD"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.state["order_send_calls"], 1)

    def test_foreign_comment_is_not_treated_as_replay(self):
        """A human comment like 'Hermes' must not be mistaken for a key."""
        self.state["order_send_calls"] = 0
        r1 = self._post({"type": "buy", "volume": 0.01,
                         "comment": "Hermes"})
        r2 = self._post({"type": "buy", "volume": 0.01,
                         "comment": "Hermes"})
        self.assertEqual(self.state["order_send_calls"], 2)
        self.assertEqual(r1.get_json()["ticket"], r2.get_json()["ticket"] - 1)

    def test_corrupt_ledger_does_not_stop_trading(self):
        """Fail-safe: a broken ledger must degrade to keyless behaviour, not
        refuse every order (that would turn the guard into an outage)."""
        with open(self.ledger, "w") as f:
            f.write("{not valid json")
        try:
            r = self._post({"type": "buy", "volume": 0.02, "symbol": "XAUUSD",
                            "sl": 4400.0, "tp": 4450.0,
                            "comment": "hms" + "d" * 10})
            self.assertEqual(r.status_code, 200)
        finally:
            os.remove(self.ledger)

    def test_ledger_is_persisted_between_requests(self):
        payload = {"type": "buy", "volume": 0.02, "symbol": "XAUUSD",
                   "sl": 4400.0, "tp": 4450.0,
                   "comment": "hms" + "e" * 10}
        self._post(payload)
        with open(self.ledger) as f:
            ledger = json.load(f)
        self.assertIn("hms" + "e" * 10, ledger)

    def test_ledger_bounded(self):
        """The ledger must not grow without limit across months of trading."""
        key = "hms" + "f" * 10
        self._post({"type": "buy", "volume": 0.01, "comment": key})
        # write a large number of distinct keys
        for i in range(60):
            self._post({"type": "buy", "volume": 0.01,
                        "comment": f"hms{i:010d}"})
        with open(self.ledger) as f:
            ledger = json.load(f)
        self.assertLessEqual(len(ledger), self.bridge._IDEM_MAX_ENTRIES)


if __name__ == "__main__":
    unittest.main()
