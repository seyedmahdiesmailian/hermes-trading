"""b68 round 10 (day-extension geometry x same-day PD-break oracle — the
REVERSED pairing of round 9) — integrity pins.

Built on the b71 harness and the b72/b73 combination playbook, so the pins
cover the round's own logic plus the ledger contract:

1. combo() is a PURE INTERSECTION: geometry comes from dayext_cont_a10
   unchanged; the same-day PD break is only a direction oracle. A
   disagreement or a silent oracle must return None, and an agreement must
   return the dayext dict byte-identical (no new stop geometry can sneak in).
2. The three cut arms (agree / disagree / notyet) are an EXACT partition of
   the dayext signal set: every signal lands in exactly one of them.
3. pd_break_info() consumes only bars <= i-1: mutating the ENTRY bar cannot
   change the oracle's answer, and the level it carries is the broken one.
4. Anti-vacuity from the SHIPPED JSONs: the gate fires on ~62% of dayext
   signals on BOTH sets (not a no-op, not a wholesale cut) and the disagree
   arm is a real sample (>50) — unlike round 9's degenerate split, this
   direction of the pairing has a genuine opposite-path subset.
5. SELECTION pin on both sets: agree > control > disagree — the oracle
   removes the WORST dayext trades, and the lift REPRODUCES fresh (the
   round's core positive finding) even though the level is far below the
   funnel (the round's verdict).
6. The b71 contract on the shipped ledgers: ladder_ts + hold columns on
   every arm row, honesty summary empty, control reproduces round 6's
   cached 0.327R n=407 (same signal, same harness).
7. STRETCH pin (the round's explanatory finding): agree entries sit ~4 ATR
   from the broken level — the path trigger fires HOURS after the level
   break, so the reversed pairing pays a chase tax. This is the mirror of
   round 8: geometry should be the FRESHER event, oracle the background.
8. rebind() repoints ALL ingredient modules and rebuilds the day LEVELS.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68k_pdh_dayext_lab as lab  # noqa: E402

LEDGER = os.path.join(ROOT, "data", "backtest", "b68k_pdh_dayext_lab.json")
CONFIRM = os.path.join(ROOT, "data", "backtest", "b68k_pdh_dayext_confirm.json")
ARMS = ("dayext_a10_control", "dayext_pdbreak_agree",
        "dayext_pdbreak_dis", "dayext_pdbreak_not")


def _load():
    with open(LEDGER) as f:
        return json.load(f)


def _confirm():
    with open(CONFIRM) as f:
        return json.load(f)


class TestComboIsPureIntersection(unittest.TestCase):
    def setUp(self):
        self.saved = (lab.dl.dayext, lab.pd_break_info)

    def tearDown(self):
        lab.dl.dayext, lab.pd_break_info = self.saved

    def test_agreement_returns_the_dayext_dict_unchanged(self):
        sig = {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 102.0,
               "style": "dayext_cont", "grade": "B"}
        lab.dl.dayext = lambda i, m="cont", st="atr", ext=1.5: sig
        lab.pd_break_info = lambda i: ("BUY", 98.5)
        self.assertIs(lab.combo(50), sig)   # same object — zero mutation

    def test_disagreement_is_dropped(self):
        sig = {"side": "BUY", "entry": 100.0}
        lab.dl.dayext = lambda i, m="cont", st="atr", ext=1.5: sig
        lab.pd_break_info = lambda i: ("SELL", 101.0)
        self.assertIsNone(lab.combo(50))

    def test_silent_oracle_is_dropped(self):
        sig = {"side": "BUY", "entry": 100.0}
        lab.dl.dayext = lambda i, m="cont", st="atr", ext=1.5: sig
        lab.pd_break_info = lambda i: None
        self.assertIsNone(lab.combo(50))

    def test_no_dayext_signal_short_circuits_the_gate(self):
        called = []
        lab.dl.dayext = lambda i, m="cont", st="atr", ext=1.5: None
        lab.pd_break_info = lambda i: (called.append(i) or ("BUY", 1.0))
        self.assertIsNone(lab.combo(50))
        self.assertEqual(called, [])   # oracle never consulted — pure AND


class TestCutIsExactPartition(unittest.TestCase):
    def setUp(self):
        self.saved = (lab.dl.dayext, lab.pd_break_info)

    def tearDown(self):
        lab.dl.dayext, lab.pd_break_info = self.saved

    def _stub(self, sig, oracle):
        lab.dl.dayext = lambda i, m="cont", st="atr", ext=1.5: sig
        lab.pd_break_info = lambda i: oracle

    def test_every_signal_lands_in_exactly_one_arm(self):
        sig = {"side": "BUY", "entry": 100.0}
        for oracle, winner in ((("BUY", 99.0), "agree"),
                               (("SELL", 101.0), "dis"),
                               (None, "not")):
            self._stub(sig, oracle)
            hits = [lab.combo(50) is not None,
                    lab.opposed(50) is not None,
                    lab.notbroken(50) is not None]
            self.assertEqual(sum(hits), 1, oracle)
            self.assertEqual(["agree", "dis", "not"][hits.index(True)], winner)

    def test_no_signal_is_no_signal_in_all_three(self):
        self._stub(None, ("BUY", 99.0))
        self.assertIsNone(lab.combo(50))
        self.assertIsNone(lab.opposed(50))
        self.assertIsNone(lab.notbroken(50))


class TestOracleNoLookahead(unittest.TestCase):
    def test_entry_bar_mutation_cannot_change_the_answer(self):
        # Synthetic day: flat then a close ABOVE the previous day's high at
        # bar 40 — the oracle must report BUY from bars <= i-1 only.
        rows = [{"time": 1784109600 + 900 * n, "open": 100.0, "high": 100.5,
                 "low": 99.5, "close": 100.0} for n in range(45)]
        saved = lab.M15, lab.IDX, lab.pl.LEVELS
        try:
            lab.rebind(rows)
            day = lab.pl.trading_day(rows[41]["time"])
            lab.pl.LEVELS[day] = (100.2, 99.0)      # PDH just above the flat
            rows[41] = dict(rows[41], close=101.0)  # bar 41 CLOSES THROUGH
            i = 43
            before = lab.pd_break_side(i)
            self.assertEqual(before, "BUY")
            rows[i] = dict(rows[i], open=9999.0, high=9999.0, low=9999.0,
                           close=9999.0)            # poison the ENTRY bar
            self.assertEqual(lab.pd_break_side(i), before)
        finally:
            lab.rebind(saved[0])
            lab.pl.LEVELS = saved[2]

    def test_oracle_carries_the_broken_level(self):
        # the level the oracle returns must be one of THAT day's two PD
        # extremes — the actual broken reference, not an arbitrary price.
        rows = lab.M15
        found = 0
        for i in range(30, len(rows)):
            info = lab.pd_break_info(i)
            if not info:
                continue
            day = lab.pl.trading_day(rows[i - 1]["time"])
            self.assertIn(day, lab.pl.LEVELS)
            self.assertIn(info[1], lab.pl.LEVELS[day])
            want = lab.pl.LEVELS[day][0] if info[0] == "BUY" else lab.pl.LEVELS[day][1]
            self.assertEqual(info[1], want)
            found += 1
            if found >= 20:
                break
        self.assertGreater(found, 5)


class TestShippedLedger(unittest.TestCase):
    def test_b71_contract_on_every_arm_row(self):
        res = _load()
        limit = res["_time_stop_bars"]
        self.assertEqual(limit, 144)          # 36h / M15 spacing
        for arm in ARMS:
            row = res[arm]
            self.assertIn("ladder_ts", row)
            for mode in ("plain", "ladder", "ladder_ts"):
                s = row[mode]
                self.assertGreater(s["trades"], 0, f"{arm}:{mode} fired 0")
                for col in ("mean_hold_bars", "p95_hold_bars",
                            "max_hold_bars", "holds_over_time_exit"):
                    self.assertIsNotNone(s[col], f"{arm}:{mode}.{col}")

    def test_round_passed_its_own_honesty_gate(self):
        self.assertEqual(_load()["_honesty_complaints"], [])

    def test_control_reproduces_round6_cached_number(self):
        # dayext_cont_a10 on the cached set was round 6's ladder +0.327R
        # n=407 (re-confirmed by the b71 recheck ledger). Same signal, same
        # harness — if the rebind or the harness drifted, this breaks.
        c = _load()["dayext_a10_control"]["ladder"]
        self.assertEqual(c["trades"], 407)
        self.assertAlmostEqual(c["exp_R"], 0.327, places=3)

    def test_gate_is_neither_noop_nor_wholesale_cut(self):
        p = _load()["_probe"]
        self.assertGreater(p["dayext_signals"], 1000)
        self.assertLess(p["gate_share"], 0.8)      # filters hard
        self.assertGreater(p["gate_share"], 0.3)   # ...but is not rare
        self.assertGreater(p["disagree"], 50)      # a real opposite-path arm
        self.assertGreater(p["no_break_yet"], 50)  # a real no-info arm

    def test_selection_is_real_gated_beats_control_beats_disagree(self):
        r = _load()
        gated = r["dayext_pdbreak_agree"]["ladder"]
        ctrl = r["dayext_a10_control"]["ladder"]
        dis = r["dayext_pdbreak_dis"]["ladder"]
        # The gate lifts its control AND the lift is explained by what it
        # DROPS: the disagree arm is the worst of the family. If disagree
        # were above the control, the lift would be a lucky-subset artefact.
        self.assertGreater(gated["exp_R"], ctrl["exp_R"])
        self.assertLess(dis["exp_R"], ctrl["exp_R"])
        self.assertGreater(dis["trades"], 50)


class TestShippedConfirmLedger(unittest.TestCase):
    """The fresh-set confirm (scripts/b68k_confirm_pdh_dayext.py) settles the
    round's merit bar; pin its numbers so the loop's SECOND reversed-pairing
    data point is never quoted without its sample sizes."""

    def test_confirm_ledger_is_honest_and_complete(self):
        c = _confirm()
        self.assertEqual(c["_honesty_complaints"], [])
        self.assertEqual(c["_time_stop_bars"], 144)
        for arm in ARMS + ("CURRENT_FUNNEL", "lane_funnel_then_agree"):
            self.assertIn("ladder_ts", c[arm], arm)

    def test_reversed_pairing_loses_the_merit_bar_on_both_sets(self):
        r, c = _load(), _confirm()
        # cached: gated 0.369 vs funnel 0.854 — fails 2.3x
        self.assertLess(r["dayext_pdbreak_agree"]["ladder_ts"]["exp_R"], 0.854)
        # fresh: gated 0.371 vs funnel 0.590 on the SAME bars — fails again
        funnel = c["CURRENT_FUNNEL"]["ladder_ts"]
        gated = c["dayext_pdbreak_agree"]["ladder_ts"]
        self.assertLess(gated["exp_R"], funnel["exp_R"])
        self.assertGreater(gated["trades"], 300)   # a real sample, not n=40

    def test_gate_lift_reproduces_on_fresh(self):
        # The round's positive finding: agree > control on BOTH sets, and
        # disagree is the worst on BOTH sets — the selection is a property,
        # not a cached-set fluke (unlike round 8 whose gate lowered control).
        r, c = _load(), _confirm()
        self.assertGreater(r["dayext_pdbreak_agree"]["ladder_ts"]["exp_R"],
                           r["dayext_a10_control"]["ladder_ts"]["exp_R"])
        self.assertGreater(c["dayext_pdbreak_agree"]["ladder_ts"]["exp_R"],
                           c["dayext_a10_control"]["ladder_ts"]["exp_R"])
        self.assertLess(c["dayext_pdbreak_dis"]["ladder_ts"]["exp_R"],
                        c["dayext_a10_control"]["ladder_ts"]["exp_R"])

    def test_lane_is_negative_on_per_trade_R_and_DD(self):
        c = _confirm()
        funnel = c["CURRENT_FUNNEL"]["ladder_ts"]
        lane = c["lane_funnel_then_agree"]["ladder_ts"]
        # The lane adds volume (n 531 vs 323) and tot_R (250 vs 191) but
        # DILUTES per-trade R (0.471 < 0.590) and doubles DD (-12.6 vs -5.0)
        # — feeds b70 as a NEGATIVE lane candidate, like rounds 6/7/8.
        self.assertLess(lane["exp_R"], funnel["exp_R"])
        self.assertLess(lane["maxDD_R"], funnel["maxDD_R"])   # more negative
        self.assertGreater(lane["trades"], funnel["trades"])

    def test_stretch_probe_shows_the_chase_tax(self):
        # b73 standard probe, the round's explanatory finding: agree entries
        # sit ~4 ATR from the broken level (median ~2.9) because the
        # extension trigger prints HOURS after the break. Round 9's forward
        # pairing entered at 0.56 ATR from the level — fresh information.
        # The reversed pairing pays for stale confirmation.
        s = _confirm()["_stretch_probe"]
        self.assertGreater(s["agree"]["mean_stretch_atr"], 2.0)
        self.assertGreater(s["agree"]["n"], 1000)
        self.assertGreater(s["disagree"]["n"], 100)

    def test_fresh_gate_probe_matches_cached_shape(self):
        p = _confirm()["_gate_probe"]
        self.assertGreater(p["dayext_signals"], 1500)
        self.assertLess(p["gate_share"], 0.8)
        self.assertGreater(p["disagree"], 100)


if __name__ == "__main__":
    unittest.main()
