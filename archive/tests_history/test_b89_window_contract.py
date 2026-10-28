"""b89 — DEFCON WINDOW: DEALS vs TRADES, REVERSED in b233b.

b89 executed option (b): it kept the unfiltered deal-level slice and wrote the
contract down as deliberate, deferring the open filter (option (a)) to a human
decision because it TIGHTENS the only feedback-loop gate globally.

b233b took that decision. The reason it had to be taken: with the deal-level
slice, a one-position book alternates open/close, so the 10-deal window held
exactly 5 exits and `sl_ratio`'s denominator was half what the classifier's own
prose assumed. The b88 re-measure proved the consequence — the live policy
never left GREEN (W1: GREEN 37 / YELLOW 0 / RED 0), while the corrected slice
on the same book went GREEN 14 / YELLOW 22 / RED 1. DEFCON was half-blind by
construction, not by intent.

The contract as of b233b, measured by scripts/b89_window_contract.py against
the LIVE producer (engines/risk.compute_performance_state) and the LIVE
classifier (engines/defcon.compute_insights) — never restated here:

  1. `recent_closed` is the last 10 EXITS of the bridge history feed, opening
     deals (entry==0, profit 0.0) filtered out by compute_performance_state.
     The cap is still 10 DEALS' worth of history, so a full window holds 10
     exits, not 5.
  2. engines/defcon's `total` is an EXIT count and `sl_ratio`'s denominator is
     exits. In a full window RED still needs sl_ratio >= 0.5, but that is now
     HALF the exits at SL instead of ALL of them — the window is twice as
     sensitive to a losing book as it was.
  3. The streak arm was unaffected (opening deals carry profit 0.0 and fired
     neither branch), so loss_streak was always exact; only the ratio arm was
     diluted. The b88 numbers above are the measured direction and magnitude.

If any of these stops being true — someone unfilters opens, changes the window
length, or moves a threshold — a test here goes red and points at
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
    # b233b: the live producer filters opening deals out of recent_closed
    # (engines/risk.compute_performance_state). Mirror it here so the levels
    # this file asserts on are the levels the gate actually computes.
    from engines.defcon import classify_exits, compute_insights
    from engines.risk import _entry_value
    deals = [d for d in deals if not _entry_value(d)]
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
        # b233b: opens are filtered out now, so a full window is 10 EXITS
        # (built from 20 deals, 10 opens + 10 closes). The contract moved from
        # deal-level to trade-level, which is why b89's pins changed shape.
        w = self._window(10)
        self.assertEqual(len(w), WINDOW_DEALS)
        exits = [d for d in w if str(d.get("entry")) != "0"]
        self.assertEqual(len(exits), WINDOW_DEALS,
                         "DEFCON's window no longer holds 10 closed trades — "
                         "the TRADES-level contract changed; re-run "
                         "scripts/b89_window_contract.py and update "
                         "engines/risk.py + engines/defcon.py together")

    def test_short_feed_keeps_every_exit_available(self):
        # 3 trips = 6 deals, 3 exits after the open filter. The window is the
        # whole feed — nothing is lost to the tail slice.
        w = self._window(3)
        self.assertEqual(len(w), 3)
        self.assertEqual(sum(1 for d in w if str(d.get("entry")) != "0"), 3)

    def test_slice_is_closing_deals_only(self):
        # b233b executed option (a) of b89: opens are filtered inside
        # compute_performance_state. This was the gate tightening b89 deferred
        # to a human; the b88 re-measure priced it (W1: GREEN 37 -> 14) and it
        # is deliberate. If this test goes red, the filter regressed and DEFCON
        # goes half-blind again.
        w = self._window(8)
        opens = [d for d in w if str(d.get("entry")) == "0"]
        self.assertEqual(len(opens), 0)


class TestDealDenominator(unittest.TestCase):
    """What the exit-level denominator does to the SL arms (probe C/D).

    b233b: the denominator is EXITS now, so the ratios below are 2x the
    deal-level numbers b89 recorded. 5 SLs of 10 deals was 0.5; 5 SLs of 5
    exits is 1.0, and one non-SL exit costs 0.2 not 0.1.
    """

    def test_full_alternating_window_needs_every_exit_sl_for_red(self):
        # 5 trips, all SL -> 5 exits, 5 SLs = ratio 1.0 -> RED
        deals = _feed(5, sl_at_end=5)[-WINDOW_DEALS:]
        ins = _level(deals)
        self.assertEqual(ins["defcon"], "RED")
        self.assertEqual(ins["exit_stats"]["total"], 5)
        self.assertEqual(ins["exit_stats"]["sl_ratio"], 1.0)

    def test_one_non_sl_exit_inside_breaks_sl_dominance(self):
        # 4 SL trips + 1 TP trip = 5 exits: 4/5 = 0.8 is still sl_dominant, so
        # RED. One non-SL exit costs 0.2, not 0.1 — the window is half as
        # forgiving as it was under the deal-level denominator.
        deals = _feed(5, sl_at_end=4)[-WINDOW_DEALS:]
        ins = _level(deals)
        self.assertGreaterEqual(ins["exit_stats"]["sl_ratio"], 0.5)
        self.assertEqual(ins["defcon"], "RED")

    def test_yellow_sl_arm_needs_half_the_exits(self):
        # 3 trips all SL = 3 exits: total>=3 passes, 3/3 = 1.0 -> YELLOW. The
        # exit-level denominator halves the window's tolerance, so this arm now
        # fires on a 3-exit book where it needed 6 deals before.
        deals = _feed(3, sl_at_end=3)[-WINDOW_DEALS:]
        ins = _level(deals)
        self.assertEqual(ins["defcon"], "YELLOW")
        # 2 trips both SL = 2 exits: total>=3 does NOT pass -> GREEN
        self.assertEqual(_level(_feed(2, sl_at_end=2)[-WINDOW_DEALS:])["defcon"],
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
        # b233b: opens are filtered out, so deals == exits and opens is 0.
        # The tail cap still bites at 20 trips (10-deal window) — that is the
        # one shape the cap ever reaches.
        shapes = {r["feed_trips"]: r for r in self.led["producer_window_shape"]}
        self.assertEqual(shapes[8]["window_deals"], 8)
        self.assertEqual(shapes[8]["window_exits"], 8)
        self.assertEqual(shapes[8]["window_opens"], 0)
        self.assertEqual(shapes[20]["window_deals"], 10)

    def test_live_window_snapshot_is_exit_shaped(self):
        lw = self.led["live_window"]
        if not lw.get("present"):
            self.skipTest("no live performance_state.json on this host")
        # b233b: `total` DEFCON sees is now the EXIT count, never the deal
        # count. If this flips back, the open filter regressed and DEFCON goes
        # half-blind again (see b88).
        self.assertEqual(lw["total_as_defcon_sees_it"], lw["window_exits"])


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
