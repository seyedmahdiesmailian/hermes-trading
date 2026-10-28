"""b205 (2026-09-10) — the post-TP1 breakeven move is a RATCHET too.

RENUMBER NOTE: the killed run that parked this fix labeled it "b204"; that
token had already been claimed by b183's procedure item the same morning
(commit 3248234). The harvest run renamed the files and stamps to b205 —
same lesson family as b203: verify tokens/claims before trusting parked labels.

b202 pinned the trail_stop branch against the funnel's `cand > t["sl"]` rule;
this file pins the sibling verb. `move_stop_to_breakeven` was gated only on
the b44/b52 MARKET-gap guard, so after the news-lock guard (legacy_guards,
which DOES enforce `protective`) tightened SL pre-TP1, a BE proposal of
entry+0.15R shipped a modify that LOOSENED the accepted stop by $46.8 on the
probe geometry (scripts/b205_be_ratchet_probe.py) — refunding news protection
into the highest-volatility window of the session. The live-parity funnel
prices BE exactly once (`t["sl"] = t["entry"]` only when the stop is worse
than entry), so any branch that can move a BETTER stop backwards is pure
lab/live drift, independent of which caller set the better stop.

Fix: `improves = new_sl > sl if side_buy else new_sl < sl`, and a
not-improving proposal falls through silently (an early hold RETURN would
starve the runner-trail branch below, which BE is evaluated before).
"""
import os
import sys
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines.trade_management import evaluate_trade_management  # noqa: E402

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _trade(side, sl, **over):
    t = {"side": side, "entry_price": 4430.0, "sl": sl,
         "tp_levels": [4495.0, 4560.0], "filled_tp_levels": [4495.0],
         "grade": 2, "momentum_strength": 0.7, "atr": 6.0,
         "breakeven_active": False, "thesis_valid": True}
    t.update(over)
    return t


class TestB204BeRatchet(unittest.TestCase):
    def test_buy_be_cannot_loosen_a_tighter_news_lock_sl(self):
        # probe geometry: lock accepted at 4485, BE would propose 4438.25
        t = _trade("BUY", 4485.0)
        m = evaluate_trade_management(t, market_price=4492.0, now=NOW)
        self.assertNotEqual(m.get("action"), "move_stop_to_breakeven",
                            "BE moved a BUY stop DOWN from an accepted "
                            "news-lock level — b205 loosening shipped")

    def test_sell_be_cannot_loosen_a_tighter_news_lock_sl(self):
        # mirrored: entry 4430 SELL, lock at 4375, BE proposes 4421.75
        t = _trade("SELL", 4375.0)
        t["tp_levels"] = [4365.0, 4300.0]
        t["filled_tp_levels"] = [4365.0]
        m = evaluate_trade_management(t, market_price=4358.0, now=NOW)
        self.assertNotEqual(m.get("action"), "move_stop_to_breakeven",
                            "BE moved a SELL stop UP from an accepted "
                            "news-lock level — b205 loosening shipped")

    def test_be_still_fires_from_the_original_stop(self):
        # the FIRST real BE move (sl still at the original wide stop) must
        # not be ratchet-starved: 4438.25 > 4400, market gap satisfied.
        t = _trade("BUY", 4400.0)
        m = evaluate_trade_management(t, market_price=4492.0, now=NOW)
        self.assertEqual(m["action"], "move_stop_to_breakeven")
        self.assertAlmostEqual(m["new_sl"], 4434.5)   # entry + 0.15 x risk(30)
        self.assertEqual(m["reason"], "lock_in_after_tp1")

    def test_equal_sl_is_not_resent(self):
        # funnel rule is STRICT (cand > t["sl"]): a stop already exactly at
        # the BE level must produce no modify spam.
        t = _trade("BUY", 4438.25)
        m = evaluate_trade_management(t, market_price=4492.0, now=NOW)
        self.assertNotEqual(m.get("action"), "move_stop_to_breakeven")

    def test_no_early_hold_return_starves_the_trail(self):
        # regression for the fix's own shape: when BE declines (not
        # improving) the runner-trail branch must still be reachable —
        # two filled levels + runner_active + a better trail candidate.
        t = _trade("BUY", 4485.0, filled_tp_levels=[4495.0, 4560.0],
                   runner_active=True, trail_atr_mult=1.0,
                   structure_state="healthy", momentum_strength=0.8,
                   thesis_valid=True)
        m = evaluate_trade_management(t, market_price=4560.0, now=NOW)
        self.assertEqual(m["action"], "trail_stop")


if __name__ == "__main__":
    unittest.main()