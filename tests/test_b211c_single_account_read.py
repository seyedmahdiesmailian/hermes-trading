"""b211(c) — ONE bridge.get_account() per signal decision.

THE DEFECT (filed 2026-09-10, measured 2026-10-03): run_signal_check read the
account at the top of check_signals — once per signal message — and then read
it AGAIN at line 529 before the per-signal execution loop. check_signals is
strictly read-only (verified: only get_tick/get_price_band/get_account/
get_positions, no order endpoint), so nothing between the two reads can have
changed the account and the second read is pure extra round-trip. The decision
that set trade_allowed was already taken inside check_signals on the FIRST
read; the second read only fed the executor-side policy overlay.

Why it matters: this is the b207 "ONE read per cycle" class. Every duplicate
read is another chance to see a DIFFERENT snapshot from the one the gates
voted on, and on a 192.168.10.51 bridge a round-trip is real latency in a
loop that runs every few seconds.

THE FIX: check_signals now threads its already-read account snapshot out on
each signal record as decision['_account_snapshot'], and run_signal_check
reuses the LAST one instead of re-reading. Falls back to a real read when the
snapshot is absent (other callers, tests, partial paths) so no caller is ever
handed None. This can only ever REDUCE bridge calls; the gates see the exact
snapshot the decision was taken on, which is strictly more correct.
"""
import os
import sys
import time
import unittest
from collections import Counter
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import engines.signal_listener as SL  # noqa: E402

_NOW_TS = int(datetime.now(timezone.utc).timestamp())
_MSG = {
    "update_id": 9001,
    "chat_id": "-100b211c",
    "chat_title": "t",
    "from": "x",
    "text": "SELL XAUUSD 4450 SL 4462 TP 4414",
    "date": _NOW_TS - 20,
}


class _CountingBridge:
    """Read-only fake bridge that counts get_account round-trips."""

    def __init__(self):
        self.calls = Counter()
        self.dark_account = False

    def get_account(self):
        self.calls["get_account"] += 1
        if self.dark_account:
            return {"ok": False, "error": "bridge_down"}
        return {"ok": True, "data": {"balance": 5000.0, "equity": 5000.0,
                                     "positions": 0, "margin_free": 5000.0,
                                     "margin": 0.0}}

    def get_tick(self, symbol):
        return {"ok": True, "ask": 4450.0, "bid": 4449.5}

    def get_price_band(self, symbol, hours=24):
        return {"ok": True, "min": 4400.0, "max": 4500.0}

    def get_positions(self, symbol):
        return {"ok": True, "data": []}


def _run(bridge):
    """run_signal_check on exactly one fresh signal message, read-only."""
    orig_fetch = SL.fetch_new_messages
    orig_group = SL.os.environ.get("TELEGRAM_SIGNAL_GROUP")
    # b254: the signal path dedupes on (chat_id, message_id) AND on a hash of
    # the content, persisting both to the real listener_state.json. The fixture
    # carries no message_id, so the content key is what fires — isolate state
    # or every _run() after the first silently drops the message.
    orig_load, orig_save = SL._load_state, SL._save_state
    _state = {"last_update_id": 0, "last_check": "", "seen_message_ids": {}}
    SL._load_state = lambda: dict(_state)
    SL._save_state = lambda st: _state.update(st)
    SL.fetch_new_messages = lambda: [dict(_MSG)]
    SL.os.environ["TELEGRAM_SIGNAL_GROUP"] = "-100b211c"
    # a dry_run executor must never reach an order endpoint
    try:
        return SL.run_signal_check(bridge, dry_run=True)
    finally:
        SL.fetch_new_messages = orig_fetch
        SL._load_state, SL._save_state = orig_load, orig_save
        if orig_group is None:
            SL.os.environ.pop("TELEGRAM_SIGNAL_GROUP", None)
        else:
            SL.os.environ["TELEGRAM_SIGNAL_GROUP"] = orig_group

class TestOneAccountReadPerSignal(unittest.TestCase):
    """b211(c): the fix. One signal message ⇒ at most ONE get_account() call
    across check_signals + run_signal_check combined. Before the fix this was
    two (one per message inside check_signals, then one more at the top of
    run_signal_check)."""

    def test_single_message_costs_one_account_read(self):
        bridge = _CountingBridge()
        _run(bridge)
        n = bridge.calls["get_account"]
        self.assertLessEqual(
            n, 1,
            f"b211(c): one signal message must cost at most ONE bridge.get_account() "
            f"round-trip across the whole signal path, got {n}")

    def test_snapshot_reuse_is_identical_to_a_fresh_read(self):
        """The reused snapshot must be the SAME payload a fresh read returns —
        no field dropped, no shape change, so every downstream gate sees the
        data it was written against."""
        bridge = _CountingBridge()
        res = _run(bridge)
        self.assertTrue(res.get("ok"))
        bridge.calls.clear()
        fresh = bridge.get_account()
        reused = SL._account_snapshot_payload(res)
        self.assertEqual(reused, fresh,
                         "the threaded snapshot must equal a fresh read")

    def test_dark_bridge_still_blocks_and_never_trades(self):
        """A failing account read must not be hidden by the reuse path: no
        snapshot is threaded out on a dark reply, so the caller falls back to
        a real read and still sees the failure."""
        bridge = _CountingBridge()
        bridge.dark_account = True
        res = _run(bridge)
        self.assertTrue(res.get("ok"))
        for ex in res.get("executions", []):
            self.assertFalse(ex.get("executed"),
                             "a dark bridge must never execute a signal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
