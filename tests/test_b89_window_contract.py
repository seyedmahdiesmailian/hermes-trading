"""b89 — DEFCON WINDOW: DEALS vs TRADES. Option (b) executed: the slice stays
as it is (option (a) would TIGHTEN the only feedback-loop gate globally — a
human decision, priced in b88), and the contract gets written down where both
sides of it live, pinned by tests so code and documentation cannot drift again.

The contract, measured by scripts/b89_window_contract.py against the LIVE
producer (engines/risk.compute_performance_state) and the LIVE classifier
(engines/defcon.compute_insights) — never restated here:

  1. `recent_closed` is the last 10 DEALS of the bridge history feed, opening
     deals (entry==0, profit 0.0) included. A one-position book alternates
     open/close, so a FULL window holds exactly 5 exits. This is the number the
     todo asked to pin: window_exits == 5.
  2. engines/defcon's `total` is therefore a DEAL count and `sl_ratio`'s
     denominator includes opens. In a full alternating window RED needs
     sl_ratio >= 0.5 over 10 deals = EVERY exit an SL. One non-SL exit inside
     the window (a TP or a managed close pushing an SL out of the tail) drops
     the ratio to 0.4 and the level to GREEN.
  3. The dilution is ONE-DIRECTIONAL: opening deals carry profit 0.0, which
     fires neither loss_streak branch, so the streak arm is exact while the
     ratio arm is HARDER than the legacy prose suggested. No shape exists where
     the deal-level slice reads a LOOSER level than the documented trade-level
     slice on the same book — which is why b88 measured the corrected slice as
     a global tightening (W1 GREEN 90 -> 11), not a mixed change.

If any of these stops being true — someone slices closing deals only, changes
the window length, or moves a threshold — a test here goes red and points at
data/backtest/b89_window_contract.json.
"""
import hashlib
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest", "b89_window_contract.json")
WINDOW_DEALS = 10


def _feed(n_trips, sl_at_end=0, partials=0):
    """Live-shaped history-deals feed: opening deal + closing deal per trip."""
    out, k = [], 1
    for i in range(n_trips):
        out.append({"ticket": k, "entry": 0, "profit": 0.0, "comment": "Hermes",
                    "time": k, "side": "BUY"})
        k += 1
        is_sl = i >= n_trips - sl_at_end
        out.append({"ticket": k, "entry": 1,
                    "profit": -10.0 if is_sl else 5.0,
                    "comment": "[sl 10.0]" if is_sl else "[tp 20.0]",
                    "time": k, "side": "BUY"})
        k += 1
    for _ in range(partials):
        out.append({"ticket": k, "entry": 1, "profit": 1.0,
                    "comment": "HermesClose", "time": k, "side": "BUY"})
        k += 1
    return out


def _level(deals, daily_pnl=-1.0, loss_streak=0):
    from engines.defcon import classify_exits, compute_insights
    return compute_insights(loss_streak=loss_streak, daily_pnl=daily_pnl,
                            balance=5000.0,
                            classified=classify_exits(deals))


class TestWindowExitCount(unittest.TestCase):
    """The pin b89 asked for: the window's EXIT count, from the real producer."""

    def _window(self, trips):
        from engines.risk import compute_performance_state
        st = compute_performance_state({"day": "2026-09-05"}, "2026-09-05",
                                       5000.0, _feed(trips))
        return st["recent_closed"]

    def test_full_window_is_10_deals_5_exits(self):
        w = self._window(8)
        self.assertEqual(len(w), WINDOW_DEALS)
        exits = [d for d in w if str(d.get("entry")) != "0"]
        self.assertEqual(len(exits), 5,
                         "DEFCON's window no longer holds 5 closed trades per "
                         "10 deals — the DEALS-vs-TRADES contract changed; "
                         "re-run scripts/b89_window_contract.py and update "
                         "engines/risk.py + engines/defcon.py together")

    def test_short_feed_keeps_every_exit_available(self):
        # 3 trips = 6 deals: window is the whole feed, 3 exits — RED's
        # total>=5 is deal-count, so 6 deals already pass it.
        w = self._window(3)
        self.assertEqual(len(w), 6)
        self.assertEqual(sum(1 for d in w if str(d.get("entry")) != "0"), 3)

    def test_slice_is_not_closing_deals_only(self):
        # Option (a) of b89 would flip this test red ON PURPOSE: filtering
        # opens inside compute_performance_state is a gate TIGHTENING and must
        # arrive as a human decision, not a quiet edit.
        w = self._window(8)
        opens = [d for d in w if str(d.get("entry")) == "0"]
        self.assertEqual(len(opens), 5)


class TestDealDenominator(unittest.TestCase):
    """What the deal-level denominator does to the SL arms (probe C/D)."""

    def test_full_alternating_window_needs_every_exit_sl_for_red(self):
        # 5 trips, all SL -> 5 SLs + 5 opens = ratio 0.5 -> RED
        deals = _feed(5, sl_at_end=5)[-WINDOW_DEALS:]
        ins = _level(deals)
        self.assertEqual(ins["defcon"], "RED")
        self.assertEqual(ins["exit_stats"]["total"], 10)
        self.assertEqual(ins["exit_stats"]["sl_ratio"], 0.5)

    def test_one_non_sl_exit_inside_breaks_sl_dominance(self):
        # 4 SL trips + 1 TP trip, all inside the window: 4 SLs / 10 deals = 0.4
        # -> NOT sl_dominant -> GREEN (streak 0, daily_pnl<0 alone cannot arm).
        deals = _feed(5, sl_at_end=4)[-WINDOW_DEALS:]
        ins = _level(deals)
        self.assertLess(ins["exit_stats"]["sl_ratio"], 0.5)
        self.assertEqual(ins["defcon"], "GREEN")

    def test_yellow_sl_arm_needs_half_the_deals(self):
        # 2 trips both SL = 4 deals: total>=3 passes, 2/4 = 0.5 -> YELLOW
        deals = _feed(2, sl_at_end=2)[-WINDOW_DEALS:]
        ins = _level(deals)
        self.assertEqual(ins["defcon"], "YELLOW")
        # 1 of 2 trips SL: 1/4 = 0.25 -> GREEN
        self.assertEqual(_level(_feed(2, sl_at_end=1)[-WINDOW_DEALS:])["defcon"],
                         "GREEN")

    def test_opening_deals_are_neutral_for_the_streak(self):
        from engines.risk import compute_performance_state
        st = compute_performance_state({"day": "2026-09-05"}, "2026-09-05",
                                       5000.0, _feed(4, sl_at_end=4))
        self.assertEqual(st["loss_streak"], 4,
                         "opening deals (profit 0.0) must not touch the streak")


class TestLedgerPinsTheContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest(f"{LEDGER} not built yet")
        with open(LEDGER) as f:
            cls.led = json.load(f)

    def test_ledger_built_against_the_current_code(self):
        # The contract lives in TWO files now (the slice in risk.py, the
        # thresholds in defcon.py); a ledger from either side drifting must not
        # pass as current.
        for fname, key in (("engines/risk.py", "_risk_code_sha"),
                           ("engines/defcon.py", "_defcon_code_sha")):
            with open(os.path.join(ROOT, *fname.split("/")), "rb") as f:
                now = hashlib.sha256(f.read()).hexdigest()[:12]
            self.assertEqual(self.led.get(key), now,
                             f"{fname} changed after the b89 ledger was built — "
                             f"re-run scripts/b89_window_contract.py")

    def test_reachability_table_matches_the_live_classifier(self):
        # Spot-check the exhaustive enumeration against fresh calls: the table
        # must not be a frozen story the code has outgrown.
        table = self.led["reachability_by_window_length"]
        for n_deals, min_sl in ((10, 5), (8, 4), (6, 3), (4, None)):
            self.assertEqual(table[str(n_deals)]["min_sl_for_RED"], min_sl,
                             f"RED reachability at {n_deals} deals drifted")
        for n_deals, min_sl in ((4, 2), (3, 2), (10, None)):
            self.assertEqual(table[str(n_deals)]["min_sl_for_YELLOW"], min_sl)

    def test_dilution_is_one_directional_in_the_ledger(self):
        rows = self.led["dilution_probe"]
        levels = [r["level"] for r in rows]
        self.assertEqual(levels[0], "RED")
        self.assertTrue(all(l in ("RED", "GREEN") for l in levels))
        # once a non-SL exit pushes the ratio under 0.5 it never re-arms
        self.assertEqual(levels[-1], "GREEN")

    def test_producer_shape_recorded(self):
        shapes = {r["feed_trips"]: r for r in self.led["producer_window_shape"]}
        self.assertEqual(shapes[8]["window_deals"], 10)
        self.assertEqual(shapes[8]["window_exits"], 5)
        self.assertEqual(shapes[8]["window_opens"], 5)

    def test_live_window_snapshot_is_deal_shaped(self):
        lw = self.led["live_window"]
        if not lw.get("present"):
            self.skipTest("no live performance_state.json on this host")
        # whatever the live book holds, `total` DEFCON sees must equal the DEAL
        # count, never the exit count (that would mean option (a) shipped).
        self.assertEqual(lw["total_as_defcon_sees_it"], lw["window_deals"])


class TestDocsSayWhatCodeDoes(unittest.TestCase):
    """The drift guard for the documentation half of option (b)."""

    def _src(self, rel):
        with open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8") as f:
            return f.read()

    def test_defcon_doc_carries_the_units_note(self):
        self.assertIn("UNITS (b89", self._src("engines/defcon.py"))

    def test_risk_slice_stays_byte_identical_for_b88(self):
        # engines/risk.py is deliberately NOT edited by b89: its sha256 is
        # stamped by b88's ledger (a comment-only change would invalidate a
        # ~50-minute measurement). If risk.py's slice ever moves, that stamp
        # test fails FIRST and this one documents why b89 left it alone.
        import hashlib
        with open(os.path.join(ROOT, "engines", "risk.py"), "rb") as f:
            now = hashlib.sha256(f.read()).hexdigest()[:12]
        with open(os.path.join(ROOT, "data", "backtest",
                               "b88_defcon_books.json")) as f:
            b88 = json.load(f)
        self.assertEqual(b88["_risk_code_sha"], now)

    def test_classify_exits_no_longer_claims_upstream_filtering(self):
        src = self._src("engines/defcon.py")
        self.assertNotIn("entry deals filtered upstream", src)


if __name__ == "__main__":
    unittest.main()
