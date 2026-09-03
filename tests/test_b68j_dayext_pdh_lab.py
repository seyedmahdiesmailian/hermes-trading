"""b68 round 9 (PDH x day-extension combination lab) — integrity pins.

Built on the b71 harness and the b72/b73 combination playbook, so the pins
cover the round's own logic plus the ledger contract:

1. combo() is a PURE INTERSECTION: geometry comes from pdh_break unchanged;
   the dayext arm is only a direction oracle. A disagreement or a silent gate
   must return None, and an agreement must return the pdh dict byte-identical
   (no new stop geometry can sneak in — the b69/round-6 trap class).
2. complement() is the exact logical complement of combo() over the pdh
   signal set: every pdh signal lands in gated XOR notyet, never both.
3. dayext_dir() consumes only bars <= i-1: mutating the ENTRY bar cannot
   change the oracle's answer (the side is fixed by the signal bar's close vs
   the day open; the 'atr' stop variant keeps risk = 1.0*ATR > 0 so the
   oracle can never silently drop on geometry — the b69 trap class).
4. Anti-vacuity from the SHIPPED JSON: the gate must actually filter
   (gate_share well under 1) and must leave a real complement (not_yet > 10).
   The agree/disagree split is DEGENERATE by construction (disagree == 0 —
   a PDH break on an extended day is directionally automatic); this round
   pins that fact and measures the dropped set directly instead.
5. SELECTION pin: gated > control > complement on cached ladder — the gate
   removes the WORST pdh trades, which is what makes the lift real rather
   than a lucky subset.
6. The b71 contract on the shipped ledger: ladder_ts + hold columns on every
   arm row, honesty summary empty, control reproduces round 4's cached
   0.627R n=54.
7. rebind() repoints ALL ingredient modules (pdh + dayext) and rebuilds the
   day LEVELS from the new bars.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68j_dayext_pdh_lab as lab  # noqa: E402

LEDGER = os.path.join(ROOT, "data", "backtest", "b68j_dayext_pdh_lab.json")
ARMS = ("pdh_w10_control", "pdh_dayext_agree", "pdh_dayext_agree_e25",
        "pdh_dayext_notyet")


def _load():
    with open(LEDGER) as f:
        return json.load(f)


class TestComboIsPureIntersection(unittest.TestCase):
    def setUp(self):
        self.saved = (lab.pl.pdh_break, lab.dl.dayext)

    def tearDown(self):
        lab.pl.pdh_break, lab.dl.dayext = self.saved

    def test_agreement_returns_the_pdh_dict_unchanged(self):
        sig = {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 102.0,
               "style": "pdh_break", "grade": "B"}
        lab.pl.pdh_break = lambda i, s=1.0: sig
        lab.dl.dayext = lambda i, m="cont", st="atr", ext=1.5: {"side": "BUY"}
        self.assertIs(lab.combo(50, 1.5), sig)   # same object — zero mutation

    def test_disagreement_is_dropped(self):
        sig = {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 102.0}
        lab.pl.pdh_break = lambda i, s=1.0: sig
        lab.dl.dayext = lambda i, m="cont", st="atr", ext=1.5: {"side": "SELL"}
        self.assertIsNone(lab.combo(50, 1.5))

    def test_silent_gate_is_dropped(self):
        sig = {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 102.0}
        lab.pl.pdh_break = lambda i, s=1.0: sig
        lab.dl.dayext = lambda i, m="cont", st="atr", ext=1.5: None
        self.assertIsNone(lab.combo(50, 1.5))

    def test_no_pdh_signal_short_circuits_the_gate(self):
        called = []
        lab.pl.pdh_break = lambda i, s=1.0: None
        lab.dl.dayext = lambda i, m="cont", st="atr", ext=1.5: (
            called.append(i) or {"side": "BUY"})
        self.assertIsNone(lab.combo(50, 1.5))
        self.assertEqual(called, [])   # gate never consulted — pure AND


class TestComplementIsExactCut(unittest.TestCase):
    def setUp(self):
        self.saved = (lab.pl.pdh_break, lab.dl.dayext)

    def tearDown(self):
        lab.pl.pdh_break, lab.dl.dayext = self.saved

    def _stub(self, sig, gate):
        lab.pl.pdh_break = lambda i, s=1.0: sig
        lab.dl.dayext = lambda i, m="cont", st="atr", ext=1.5: gate

    def test_silent_gate_keeps_the_signal(self):
        sig = {"side": "BUY", "entry": 100.0}
        self._stub(sig, None)
        self.assertIs(lab.complement(50, 1.5), sig)

    def test_agreeing_gate_drops_it(self):
        sig = {"side": "BUY", "entry": 100.0}
        self._stub(sig, {"side": "BUY"})
        self.assertIsNone(lab.complement(50, 1.5))

    def test_disagreeing_gate_drops_it_too(self):
        # complement = "oracle silent", NOT "oracle disagrees": the union of
        # combo() and complement() over the pdh set must be the whole set.
        sig = {"side": "BUY", "entry": 100.0}
        self._stub(sig, {"side": "SELL"})
        self.assertIsNone(lab.complement(50, 1.5))

    def test_no_signal_is_no_signal(self):
        self._stub(None, None)
        self.assertIsNone(lab.complement(50, 1.5))


class TestOracleNoLookahead(unittest.TestCase):
    def test_entry_bar_mutation_cannot_change_the_answer(self):
        # Build a synthetic extended up-day: 40 bars rising, day open far
        # below the last close, so the 1.5-ATR continuation gate fires BUY.
        rows = [{"time": 1784109600 + 900 * n, "open": 100.0 + 0.5 * n,
                 "high": 100.3 + 0.5 * n, "low": 99.8 + 0.5 * n,
                 "close": 100.1 + 0.5 * n} for n in range(45)]
        saved = lab.M15, lab.IDX, lab.dl.M15
        try:
            lab.rebind(rows)
            i = 42
            before = lab.dayext_dir(i, 1.0)   # loose threshold fires
            rows[i] = dict(rows[i], open=9999.0, high=9999.0, low=9999.0,
                           close=9999.0)      # poison the ENTRY bar
            self.assertEqual(lab.dayext_dir(i, 1.0), before)
        finally:
            lab.M15, lab.IDX, lab.dl.M15 = saved
            lab.rebind(lab.M15)


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

    def test_control_reproduces_round4_cached_number(self):
        # pdh_break_w10 on the cached set was round 4's ladder +0.627R n=54.
        # The control arm here is the SAME signal through the SAME harness; if
        # the harness or the rebind changed the measurement, this breaks.
        c = _load()["pdh_w10_control"]["ladder"]
        self.assertEqual(c["trades"], 54)
        self.assertAlmostEqual(c["exp_R"], 0.627, places=3)

    def test_gate_is_neither_noop_nor_wholesale_cut(self):
        p = _load()["_probe"]["e15"]
        self.assertGreater(p["pdh_signals"], 50)
        # filters hard (a no-op gate would read gate_share ~ 1)
        self.assertLess(p["gate_share"], 0.8)
        # ...and leaves a real complement to measure (not the control twice)
        self.assertGreater(p["not_yet_dropped"], 10)

    def test_degenerate_split_is_pinned_as_a_fact(self):
        # disagree == 0 by CONSTRUCTION (a close-confirmed PDH break on a day
        # already extended 1.5 ATR is directionally automatic). If a future
        # dataset ever produces a disagreement, this pin forces a re-read of
        # the round's anti-vacuity argument instead of rotting silently.
        for k in ("e15", "e25"):
            p = _load()["_probe"][k]
            self.assertEqual(p["disagree"], 0, k)
            self.assertEqual(p["agree"], p["dayext_gated"], k)

    def test_selection_is_real_gated_beats_control_beats_complement(self):
        r = _load()
        gated = r["pdh_dayext_agree"]["ladder"]
        ctrl = r["pdh_w10_control"]["ladder"]
        comp = r["pdh_dayext_notyet"]["ladder"]
        # The gate lifts its control AND the lift is explained by what it
        # DROPS: the complement is the worst of the three. If the complement
        # were above the control, the lift would be a lucky-subset artefact.
        self.assertGreater(gated["exp_R"], ctrl["exp_R"])
        self.assertLess(comp["exp_R"], ctrl["exp_R"])
        self.assertGreater(comp["trades"], 20)    # a real complement sample


class TestShippedConfirmLedger(unittest.TestCase):
    """The fresh-set confirm (scripts/b68j_confirm_dayext_pdh.py) is what
    settles the round's merit bar; pin its numbers so the loop's FIRST
    both-sets-pass claim is never quoted without its sample sizes, and so
    the first all-axes-positive lane is never quoted without b70/b74's
    replication requirement."""

    P = os.path.join(ROOT, "data", "backtest", "b68j_dayext_pdh_confirm.json")

    def _c(self):
        with open(self.P) as f:
            return json.load(f)

    def test_confirm_ledger_is_honest_and_complete(self):
        c = self._c()
        self.assertEqual(c["_honesty_complaints"], [])
        self.assertEqual(c["_time_stop_bars"], 144)
        for arm in ("CURRENT_FUNNEL", "pdh_w10_control", "pdh_dayext_agree",
                    "pdh_dayext_agree_e25", "pdh_dayext_notyet",
                    "lane_funnel_then_gated", "lane_funnel_then_gated_e25"):
            self.assertIn("ladder_ts", c[arm], arm)

    def test_gated_arm_beats_the_funnel_on_fresh_but_on_a_small_sample(self):
        c = self._c()
        funnel = c["CURRENT_FUNNEL"]["ladder_ts"]
        gated = c["pdh_dayext_agree"]["ladder_ts"]
        # merit bar PASSED on per-trade R: 0.891 > 0.590 on the SAME bars
        # (and cached 0.924 > 0.854). But n=39 vs the funnel's n=323 — the
        # pin forces every future quote to carry both facts.
        self.assertGreater(gated["exp_R"], funnel["exp_R"])
        self.assertLess(gated["trades"], funnel["trades"] // 4)
        self.assertGreater(gated["trades"], 30)     # not an n=4 fluke either
        # and the total dollars still favour the funnel: replacement on
        # volume is NOT what this arm is for.
        self.assertLess(gated["net_R"], funnel["net_R"])

    def test_selection_holds_on_fresh_complement_below_control(self):
        c = self._c()
        ctrl = c["pdh_w10_control"]["ladder_ts"]
        comp = c["pdh_dayext_notyet"]["ladder_ts"]
        self.assertLess(comp["exp_R"], ctrl["exp_R"])   # 0.467 < 0.609
        self.assertGreater(comp["trades"], 50)

    def test_lane_is_the_first_to_beat_the_funnel_on_all_three_axes(self):
        c = self._c()
        funnel = c["CURRENT_FUNNEL"]["ladder_ts"]
        lane = c["lane_funnel_then_gated"]["ladder_ts"]
        # exp_R, tot_R AND dd_R all improve — rounds 4/7/8 lanes each lost at
        # least one axis. This is the promotion CANDIDATE, still one fresh
        # set only (b70 rule: never wire on one set) -> b74 replication.
        self.assertGreater(lane["exp_R"], funnel["exp_R"])
        self.assertGreater(lane["net_R"], funnel["net_R"])
        self.assertGreater(lane["maxDD_R"], funnel["maxDD_R"])  # less negative
        self.assertGreater(lane["trades"], funnel["trades"])    # adds volume

    def test_stretch_probe_says_the_lift_is_informational_not_geometric(self):
        # b73 standard probe: round 8's compression gate damaged its arm via
        # stretch (0.667 vs 0.558 ATR). Here gated/control/notyet stretches
        # are statistically identical — the path gate selects on INFORMATION,
        # exactly the b73 prediction for path-on-path pairings.
        s = self._c()["_stretch_probe"]
        self.assertLess(abs(s["gated"]["mean_stretch_atr"]
                            - s["control"]["mean_stretch_atr"]), 0.05)
        self.assertGreater(s["gated"]["n"], 30)
        self.assertGreater(s["notyet"]["n"], 50)

    def test_fresh_gate_probe_filters_hard(self):
        p = self._c()["_gate_probe"]["e15"]
        self.assertGreater(p["pdh_signals"], 100)
        self.assertLess(p["gate_share"], 0.8)
        self.assertGreater(p["not_yet_dropped"], 50)


if __name__ == "__main__":
    unittest.main()
