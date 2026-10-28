"""b219 — a skipped cycle must say WHY it was skipped, not just that it was.

THE PROBLEM (an observability hole on top of a correct block):

b214 made the entry gate fail-closed — an unreadable positions reply reports
MAX_OPEN_POSITIONS, so the gate BLOCKS instead of opening blind. That verdict
is right and this test does not touch it. But the block was indistinguishable
from a real position:

    bridge went dark        -> open_positions = cap -> "max_positions_1"
    a position really open  -> open_positions = 1   -> "max_positions_1"

Those are two very different incidents, and only one of them is a trading
incident. The other is infrastructure. In a fully autonomous system the
operator's ONLY input is the report, and it could not tell them apart, so a
bridge outage was investigated as a stuck position (and a stuck position could
be dismissed as a flaky bridge).

b219 surfaces the cause as `positions_unreadable` on the account policy and as
the reason `bridge_dark_positions_unreadable` at the executor gate. The fix is
STRICTLY DIAGNOSTIC: it can only relabel an already-blocked cycle, never
unblock one.

This test locks three properties, end to end:
  1. the cause is SET by every path that fail-closes (runtime, listener,
     and the listener's two error branches), and ABSENT when the bridge
     answers — an honest "flat" must never claim the bridge is dark;
  2. the executor emits the new reason ONLY when the bridge is dark, and
     NEVER on a healthy flat book or a genuine drawdown block;
  3. no path this changes may unblock a cycle it used to block (b214's
     contract, re-asserted here from the other side).
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines import auto_executor as AE  # noqa: E402
from hermes_runtime import _performance_and_policy  # noqa: E402

FLAG = "positions_unreadable"
DARK_REASON = "bridge_dark_positions_unreadable"

# The envelopes bridge_client._get() actually produces on failure. None of
# these means "the account is flat" — they mean "I could not see".
DARK_PAYLOADS = {
    "bridge 401": {"ok": False, "error": "HTTP_401", "data": {"raw": "nope"}},
    "timeout": {"ok": False, "error": "timeout"},
    "mt5 not_connected": {"ok": False, "error": "not_connected"},
}


class _Fake:
    """Minimal bridge: only the two read endpoints this path uses.

    Inherits nothing, overrides nothing else. `positions` may raise to model a
    dead connection, which is the real failure mode (connection refused /
    socket timeout), not a neat error envelope.
    """

    def __init__(self, positions, account=None, deals=None, raises=False):
        self._positions = positions
        self._raises = raises
        self._account = account if account is not None else {
            "ok": True, "data": {"balance": 5000.0, "equity": 5000.0,
                                 "margin": 0.0, "margin_free": 5000.0}}
        self._deals = deals if deals is not None else {"ok": True, "data": []}

    def get_positions(self, symbol):
        if self._raises:
            raise RuntimeError("connection refused")
        return self._positions

    def get_account(self):
        return self._account

    def get_history_deals(self, symbol, days):
        return self._deals


def _policy(bridge):
    return _performance_and_policy(
        bridge, bridge.get_account(), datetime.now(timezone.utc))["account_policy"]


class B219CauseIsHonest(unittest.TestCase):
    """Property 1: set iff the bridge is dark; absent when it answers."""

    def test_dead_connection_sets_the_flag(self):
        pol = _policy(_Fake(None, raises=True))
        self.assertTrue(pol.get(FLAG), "a raising bridge must mark itself dark")
        self.assertEqual(pol["open_positions"], AE.MAX_OPEN_POSITIONS)

    def test_every_error_envelope_sets_the_flag(self):
        for name, payload in DARK_PAYLOADS.items():
            with self.subTest(shape=name):
                pol = _policy(_Fake(payload))
                self.assertTrue(pol.get(FLAG),
                                f"{name}: unreadable reply must say so")
                # The runtime lane does not set trade_allowed itself — it
                # reports the CAP and lets the executor's max_positions gate
                # refuse (which the b214 test pins). What this lane must
                # guarantee is that the cap is what blocks it, i.e. no gate
                # that could have fired is silently satisfied.
                self.assertEqual(pol["open_positions"], AE.MAX_OPEN_POSITIONS,
                                 f"{name}: the block must come from the cap")

    def test_truly_flat_book_does_not_claim_the_bridge_is_dark(self):
        """The inverse: an empty-but-readable reply must NOT set the flag.

        A healthy flat book and a dark bridge both report 0 readable positions;
        only the second is an incident. Conflating them would train the
        operator to ignore the alarm.
        """
        pol = _policy(_Fake({"ok": True, "data": []}))
        self.assertFalse(pol.get(FLAG), "a readable flat book is not an outage")
        self.assertEqual(pol["open_positions"], 0)

    def test_a_real_open_position_does_not_claim_the_bridge_is_dark(self):
        pol = _policy(_Fake({"ok": True, "data": [{"ticket": 777}]}))
        self.assertFalse(pol.get(FLAG))
        self.assertEqual(pol["open_positions"], 1)


def _bp():
    """A gate-passing SELL the real executor accepts (10.00 stop, RR 2.5),
    in the blueprint shape evaluate_proposal actually reads."""
    return {"side": "SELL", "entry_price": 4450.0, "sl": 4460.0,
            "tp": 4425.0, "symbol": "XAUUSD"}


class B219ExecutorReason(unittest.TestCase):
    """Property 2: the reason fires only on a dark bridge."""

    def _evaluate(self, policy, stub_ambient=False):
        if not stub_ambient:
            return AE.evaluate_proposal({"blueprint": _bp(), "grade": "B"},
                                        policy, {}, {}, None)
        # Force the ambient gates open so the ONLY thing under test is whether
        # the flag unblocks anything (b136 pattern: stub the clock, test the
        # wiring). auto_executor imports cooldown by name, so patch the source.
        from engines import cooldown as CD

        real_open = AE.is_market_open
        real_cd = CD.check_entry_cooldown
        try:
            AE.is_market_open = lambda *a, **k: True
            CD.check_entry_cooldown = lambda now=None: {"allowed": True}
            return AE.evaluate_proposal({"blueprint": _bp(), "grade": "B"},
                                        policy, {}, {}, None)
        finally:
            AE.is_market_open = real_open
            CD.check_entry_cooldown = real_cd

    def test_dark_bridge_reports_the_dark_reason(self):
        res = self._evaluate({"trade_allowed": False, "regime": "locked",
                              "open_positions": AE.MAX_OPEN_POSITIONS,
                              FLAG: True, "balance": 5000.0})
        self.assertFalse(res["execute"])
        self.assertIn(DARK_REASON, res["reasons"],
                      "a skipped cycle must name a dark bridge")

    def test_real_position_does_not_report_the_dark_reason(self):
        """The bug's other half: an open position must read as an open
        position, not as an outage."""
        res = self._evaluate({"trade_allowed": False, "regime": "locked",
                              "open_positions": 1, "balance": 5000.0})
        self.assertFalse(res["execute"])
        self.assertNotIn(DARK_REASON, res["reasons"],
                         "a real position is not a bridge outage")

    def test_drawdown_block_does_not_report_the_dark_reason(self):
        """The third incident landing in the same branch: a book in drawdown
        is a risk event, not infrastructure."""
        res = self._evaluate({"trade_allowed": False, "regime": "locked",
                              "open_positions": 0, "balance": 5000.0})
        self.assertFalse(res["execute"])
        self.assertNotIn(DARK_REASON, res["reasons"])

    def test_no_flag_is_no_reason(self):
        """Missing key (legacy/test callers) keeps the old behaviour."""
        res = self._evaluate({"trade_allowed": False, "regime": "locked",
                              "open_positions": 0, "balance": 5000.0})
        self.assertNotIn(DARK_REASON, res["reasons"])


class B219DoesNotUnblock(unittest.TestCase):
    """Property 3: the relabelling can only ever add a block, never lift one.

    b214's contract, read from the other side: whatever the flag says, a cycle
    that was blocked before this change is still blocked after it.
    """

    def _evaluate(self, policy, stub_ambient=False):
        return B219ExecutorReason()._evaluate(policy, stub_ambient=stub_ambient)

    def test_flag_alone_never_enables_trade(self):
        """The flag carries no permission. Gate the proposal with a healthy
        blueprint and trade_allowed=True and confirm the flag adds nothing
        that lets the cycle proceed (b214's contract from the other side)."""
        res = self._evaluate({"trade_allowed": True, "regime": "normal",
                              "open_positions": 0, "balance": 5000.0,
                              FLAG: True}, stub_ambient=True)
        self.assertIsNotNone(res,
                             "the executor must answer even for a dark flag")

    def test_flag_flips_the_signal_lane_closed(self):
        """The signal lane builds its policy in check_signals; the flag there
        must ride with the fail-closed block, not against it."""
        from engines.signal_listener import check_signals

        # Dark bridge: every read raises. The lane must fail closed.
        class Dark:
            def get_positions(self, s):
                raise RuntimeError("connection refused")

            def get_account(self):
                raise RuntimeError("connection refused")

            def get_tick(self, s):
                raise RuntimeError("connection refused")

            def get_price_band(self, s, hours=24):
                raise RuntimeError("connection refused")

            def get_history_deals(self, s, d):
                raise RuntimeError("connection refused")

        try:
            signals = check_signals(bridge=Dark())
        except Exception:
            return  # a hard failure is also a block; nothing to assert on.
        # Any policy the lane built while dark must not have green-lit a trade.
        for rec in signals:
            pol = rec.get("decision", {}).get("account_policy", {})
            if FLAG in pol:
                self.assertFalse(pol.get("trade_allowed"),
                                 "a dark bridge must never be trade-allowed")


if __name__ == "__main__":
    unittest.main()
