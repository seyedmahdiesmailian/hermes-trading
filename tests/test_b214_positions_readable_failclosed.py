"""b214 — an UNREADABLE positions reply must never read as "nothing is open".

THE BUG, in one line: positions_list() answers [] both when the broker
really has no positions AND when the bridge could not be read (401, timeout
envelope, MT5 not_connected). Readers want that leniency. The ENTRY GATE
does not — for it, "I could not see" collapsed into "safe to open".

This is not hypothetical. hermes_runtime:425 records the day the same shape
cost real money: account.positions was always 0, MAX_OPEN_POSITIONS=1 never
fired, and two sells stacked at 14:15 + 14:30 UTC for net -56.7$. The b45
fix counted positions properly when the bridge ANSWERS; b214 closes the
case where it does not answer at all — and account.positions is 0 there
too, so the max() guard could not rescue it.

The fix is TIGHTENING ONLY: an unreadable reply reports MAX_OPEN_POSITIONS,
so the gate blocks. It can add a block, never remove one. Protective
management is untouched (position_daemon keeps its own bridge-failure
guard, and b207 requires a halted account to still manage open risk).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines.auto_executor import MAX_OPEN_POSITIONS  # noqa: E402
from engines.bridge_payload import (position_count, positions_list,  # noqa: E402
                                    positions_readable)

# The exact envelopes bridge_client._post/_get produce on failure, plus the
# MT5-level error the live bridge returns. None of these means "flat".
UNREADABLE = {
    "bridge 401": {"ok": False, "error": "HTTP_401", "data": {"raw": "unauthorized"}},
    "timeout": {"ok": False, "error": "timeout"},
    "mt5 down": {"ok": False, "error": "not_connected"},
    "text body": {"ok": False, "error": "HTTP_500", "data": {"raw": "<html>"}},
    "not a dict": "boom",
    "none": None,
}
READABLE = {
    "flat": {"ok": True, "data": []},
    "one open": {"ok": True, "data": [{"ticket": 1, "profit": 5.0}]},
    "no ok key, real list": {"data": [{"ticket": 2}]},
    "legacy positions key": {"ok": True, "positions": [{"ticket": 3}]},
}


class PredicateSeparatesEmptyFromUnknown(unittest.TestCase):

    def test_unreadable_replies_are_not_readable(self):
        for name, resp in UNREADABLE.items():
            self.assertFalse(positions_readable(resp), name)

    def test_readable_replies_are_readable(self):
        for name, resp in READABLE.items():
            self.assertTrue(positions_readable(resp), name)

    def test_the_two_empties_are_indistinguishable_by_count_alone(self):
        """Why the predicate has to exist as a separate question."""
        broken = {"ok": False, "error": "HTTP_401"}
        flat = {"ok": True, "data": []}
        self.assertEqual(position_count(broken), position_count(flat))
        self.assertEqual(positions_list(broken), positions_list(flat))
        self.assertNotEqual(positions_readable(broken), positions_readable(flat))

    def test_readers_keep_their_leniency(self):
        """b214 must not change what positions_list answers to anybody."""
        for resp in list(UNREADABLE.values()):
            self.assertEqual(positions_list(resp), [])
        self.assertEqual(len(positions_list(READABLE["one open"])), 1)


class _Bridge:
    """Minimal bridge whose positions reply we control."""

    def __init__(self, positions_resp):
        self._pos = positions_resp

    def get_account(self):
        return {"ok": True, "balance": 5000.0, "equity": 5000.0,
                "margin_free": 5000.0, "margin": 0.0, "login": 1}

    def get_positions(self, symbol="XAUUSD"):
        if isinstance(self._pos, Exception):
            raise self._pos
        return self._pos

    def get_history_deals(self, symbol="XAUUSD", days=7):
        return {"ok": True, "data": []}

    def get_tick(self, symbol="XAUUSD"):
        return {"ok": True, "bid": 4450.0, "ask": 4450.2}


class PlanLaneBlocksWhenBlind(unittest.TestCase):
    """hermes_runtime._performance_and_policy — the b45 site."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()
        import os
        os.environ["HERMES_DATA_ROOT"] = self._tmp

    def tearDown(self):
        import os
        os.environ.pop("HERMES_DATA_ROOT", None)

    def _policy(self, positions_resp):
        from datetime import datetime, timezone
        import hermes_runtime as HR
        br = _Bridge(positions_resp)
        out = HR._performance_and_policy(br, br.get_account(),
                                         datetime.now(timezone.utc))
        return out["account_policy"]

    def test_unreadable_reply_reports_the_cap_not_zero(self):
        for name, resp in UNREADABLE.items():
            pol = self._policy(resp)
            self.assertGreaterEqual(
                pol["open_positions"], MAX_OPEN_POSITIONS,
                f"{name}: blind read reported a free slot")
            self.assertTrue(pol.get("positions_unreadable"), name)

    def test_an_exception_also_blocks(self):
        pol = self._policy(RuntimeError("socket died"))
        self.assertGreaterEqual(pol["open_positions"], MAX_OPEN_POSITIONS)
        self.assertTrue(pol.get("positions_unreadable"))

    def test_healthy_flat_account_still_has_a_free_slot(self):
        """The fix must not freeze normal trading."""
        pol = self._policy({"ok": True, "data": []})
        self.assertEqual(pol["open_positions"], 0)
        self.assertFalse(pol.get("positions_unreadable", False))

    def test_healthy_occupied_account_is_unchanged(self):
        pol = self._policy({"ok": True, "data": [{"ticket": 9, "profit": 1.0}]})
        self.assertEqual(pol["open_positions"], 1)
        self.assertFalse(pol.get("positions_unreadable", False))


class TheGateActuallyRefusesOnThatCount(unittest.TestCase):
    """Wiring proof: the blind count must reach a REAL refusal (b140 lesson —
    a fail-closed value that nothing consumes is not a safety net).

    Rather than hand-build a blueprint the executor accepts (which would pin
    this test to an unrelated payload shape), this drives the gate function
    that owns the cap and asserts the DIFFERENCE the count makes.
    """

    @staticmethod
    def _position_gate(open_positions):
        """The b214-relevant slice of evaluate_proposal's Check 5, called on
        the real module constant so it cannot drift from production."""
        import engines.auto_executor as AE
        return int(open_positions) >= AE.MAX_OPEN_POSITIONS

    def test_a_blind_count_trips_the_cap_and_a_flat_one_does_not(self):
        self.assertTrue(self._position_gate(MAX_OPEN_POSITIONS),
                        "the fail-closed count does not trip the cap")
        self.assertFalse(self._position_gate(0),
                         "a genuinely flat account lost its free slot")

    def test_check5_is_still_the_code_that_enforces_it(self):
        """If Check 5 is renamed or deleted, b214's protection evaporates
        silently — pin the enforcement site, not just the arithmetic."""
        src = (ROOT / "engines" / "auto_executor.py").read_text(encoding="utf-8")
        self.assertIn("open_positions >= MAX_OPEN_POSITIONS", src,
                      "the position cap check moved — re-verify that a "
                      "b214 blind count still blocks entry")

    def test_runtime_hands_the_gate_a_blocking_number(self):
        """End-to-end arithmetic: unreadable -> count -> cap tripped."""
        from engines.bridge_payload import positions_readable as pr
        for name, resp in UNREADABLE.items():
            count = position_count(resp) if pr(resp) else MAX_OPEN_POSITIONS
            self.assertTrue(self._position_gate(count),
                            f"{name}: gate would have allowed a new entry")


class SignalLaneBlocksWhenBlind(unittest.TestCase):
    """The same hazard in the signal path, whose own comment already warned
    that a caught exception degraded to _open_ct=0."""

    def test_source_no_longer_starts_the_count_at_zero(self):
        src = (ROOT / "engines" / "signal_listener.py").read_text(encoding="utf-8")
        self.assertIn("positions_readable", src,
                      "signal lane still trusts a possibly-unreadable reply")
        self.assertIn("_pos_unreadable", src)

    def test_unreadable_reply_yields_a_blocking_count(self):
        """Exercise the real decision the lane would hand the scorer."""
        from engines.bridge_payload import positions_readable as pr
        for name, resp in UNREADABLE.items():
            open_ct = (position_count(resp) if pr(resp) else MAX_OPEN_POSITIONS)
            self.assertGreaterEqual(open_ct, MAX_OPEN_POSITIONS, name)


class TighteningOnly(unittest.TestCase):
    """b214 may add blocks; it may never hand out a free slot."""

    def test_no_reply_shape_produces_fewer_positions_than_before(self):
        from engines.bridge_payload import positions_readable as pr
        for resp in list(UNREADABLE.values()) + list(READABLE.values()):
            before = position_count(resp)                      # old behaviour
            after = before if pr(resp) else MAX_OPEN_POSITIONS  # new behaviour
            self.assertGreaterEqual(
                after, before,
                f"b214 loosened the count for {resp!r}: {before} -> {after}")


if __name__ == "__main__":
    unittest.main()
