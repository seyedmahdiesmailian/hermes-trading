"""b68 round 11 (b68l) — TRULY INDEPENDENT windows: integrity + verdict pins.

Why this round exists (the loop's biggest methodology finding): every
confirm in rounds 1-10 fetched "the last 6000 M15 bars" as the FRESH set.
Measured here: the cached 3000-bar set sits at the END of the broker's M15
history, so the last 6000 bars contain ALL 3000 cached bars
(_last6000_overlap_with_cached == 3000). The "beat the funnel on BOTH sets"
merit bar was therefore never an out-of-sample test — it compared a set
against its own superset for ten rounds.

This file pins, from the SHIPPED JSONs (offline, deterministic):
1. Window integrity: W1/W2 are 6000 strictly-ordered bars each, zero overlap
   with the cached set and with each other, W2 < W1 < cached, and both carry
   H1/H4 context. Plus the founding contamination fact itself.
2. The b71 harness contract on every arm row of both windows (ladder_ts +
   hold columns, derived time exit = 144, empty honesty complaints).
3. The round's verdicts: round 9's champion FAILS replication (0.928 W1 vs
   0.447 W2); the gate's selection FLIPS SIGN between windows (complement
   0.415->0.743 vs agree 0.928->0.447 — regime artefact, not a property);
   the UNGATED pdh control is the ONLY arm that beats the funnel on both
   independent windows (0.612/0.623 vs 0.524/0.521); nr7 loses both; the
   gated lane replicates only a marginal positive (< +0.05R).
4. The verdict() replication logic itself, replayed on synthetic ledgers —
   the seed of b74's replication protocol: PASS requires beating the
   funnel on the SAME bars in BOTH windows, and a None exp_R (0 trades)
   never counts as a beat.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68l_confirm_independent as conf  # noqa: E402

WINDOWS = os.path.join(ROOT, "data", "backtest", "b68l_independent_windows.json")
LEDGER = os.path.join(ROOT, "data", "backtest", "b68l_independent_confirm.json")

ARMS = ("CURRENT_FUNNEL", "pdh_w10_control", "pdh_dayext_agree",
        "pdh_dayext_agree_e25", "pdh_dayext_notyet", "nr7_break_w10",
        "lane_funnel_then_gated")


def _load(path):
    with open(path) as f:
        return json.load(f)


class TestWindowIntegrity(unittest.TestCase):
    """The windows must be what the round CLAIMS they are: independent."""

    @classmethod
    def setUpClass(cls):
        cls.w = _load(WINDOWS)

    def test_old_fresh_set_was_fully_contaminated(self):
        # THE founding fact of round 11: the last-6000 "fresh" set of
        # rounds 1-10 held every single cached bar. If this number ever
        # changes, the broker history shifted and the round's premise
        # must be re-measured, not assumed.
        self.assertEqual(self.w["_last6000_overlap_with_cached"], 3000)
        self.assertEqual(self.w["_cached_bars"], 3000)

    def test_windows_have_zero_overlap_with_cached_and_each_other(self):
        for name in ("W1", "W2"):
            self.assertEqual(self.w[f"_{name}_meta"]["overlap_with_cached"], 0)
        self.assertEqual(self.w["_W1_W2_overlap"], 0)

    def test_windows_are_ordered_before_the_cached_set(self):
        c0 = self.w["_cached_span"][0]
        w1, w2 = self.w["_W1_meta"], self.w["_W2_meta"]
        self.assertEqual(w1["m15_bars"], 6000)
        self.assertEqual(w2["m15_bars"], 6000)
        self.assertLess(w2["last"], w1["first"])   # W2 strictly older
        self.assertLess(w1["last"], c0)            # W1 ends before cached
        # W1 must butt against the cached set (one bar gap), not float away
        self.assertLess(c0 - w1["last"], 2 * 900)

    def test_m15_rows_strictly_increasing(self):
        for name in ("W1", "W2"):
            ts = [int(r["time"]) for r in self.w[name]["M15"]]
            self.assertEqual(len(ts), 6000)
            self.assertTrue(all(b > a for a, b in zip(ts, ts[1:])), name)

    def test_windows_carry_htf_context(self):
        # strategy_signal needs >=80 H1/H4 bars up to each bar's time; the
        # builder pads 200h before the window — an empty context stream
        # would silently starve the funnel and fake a low baseline.
        for name in ("W1", "W2"):
            self.assertGreater(len(self.w[name]["H1"]), 1000, name)
            self.assertGreater(len(self.w[name]["H4"]), 300, name)


class TestLedgerHarnessContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = _load(LEDGER)

    def test_time_exit_derived_to_144_on_both_windows(self):
        for w in ("W1", "W2"):
            self.assertEqual(self.led[w]["_time_stop_bars"], 144)
            self.assertEqual(self.led[w]["_bars"], 6000)

    def test_every_arm_row_has_ladder_ts_and_hold_columns(self):
        for w in ("W1", "W2"):
            for arm in ARMS:
                row = self.led[w][arm]
                self.assertIn("ladder_ts", row, f"{w}/{arm}")
                for mode in ("plain", "ladder", "ladder_ts"):
                    s = row[mode]
                    for col in ("mean_hold_bars", "p95_hold_bars",
                                "max_hold_bars", "holds_over_time_exit"):
                        self.assertIsNotNone(s[col], f"{w}/{arm}:{mode}.{col}")

    def test_both_windows_passed_their_own_honesty_gate(self):
        for w in ("W1", "W2"):
            self.assertEqual(self.led[w]["_honesty_complaints"], [], w)

    def test_funnel_baseline_measured_on_the_same_bars(self):
        # round-4 rule: the funnel is re-measured per window, never quoted
        # from the cached ledger. n ~315/316 with a real sample.
        f1 = self.led["W1"]["CURRENT_FUNNEL"]["ladder_ts"]
        f2 = self.led["W2"]["CURRENT_FUNNEL"]["ladder_ts"]
        self.assertEqual((f1["trades"], f2["trades"]), (316, 315))
        self.assertAlmostEqual(f1["exp_R"], 0.524, places=3)
        self.assertAlmostEqual(f2["exp_R"], 0.521, places=3)


class TestShippedVerdicts(unittest.TestCase):
    """The round's decision-set outcomes, pinned with their sample sizes."""

    @classmethod
    def setUpClass(cls):
        cls.led = _load(LEDGER)
        cls.v = cls.led["_verdict"]

    def _r(self, w, arm):
        return self.led[w][arm]["ladder_ts"]

    def test_round9_champion_fails_replication(self):
        # 0.928 on W1 (beats funnel 0.524) but 0.447 on W2 (loses to 0.521)
        # -> the cached+contaminated-fresh pass was regime luck. b74's
        # replication requirement just earned its keep on the loop's only
        # merit-bar passer.
        self.assertGreater(self._r("W1", "pdh_dayext_agree")["exp_R"],
                           self._r("W1", "CURRENT_FUNNEL")["exp_R"])
        self.assertLess(self._r("W2", "pdh_dayext_agree")["exp_R"],
                        self._r("W2", "CURRENT_FUNNEL")["exp_R"])
        self.assertFalse(self.v["replicated_in_both"]["pdh_dayext_agree"])
        self.assertFalse(self.v["replicated_in_both"]["pdh_dayext_agree_e25"])

    def test_gate_selection_flips_sign_between_windows(self):
        # The round's deepest negative finding: agree > complement on W1
        # (0.928 vs 0.415) but agree < complement on W2 (0.447 vs 0.743).
        # Round 9's complement-probe "proof that selection is real" only
        # held in the regime it was discovered in — the dayext gate is not
        # a property of gold M15, it is a regime interaction.
        a1, c1 = (self._r("W1", "pdh_dayext_agree")["exp_R"],
                  self._r("W1", "pdh_dayext_notyet")["exp_R"])
        a2, c2 = (self._r("W2", "pdh_dayext_agree")["exp_R"],
                  self._r("W2", "pdh_dayext_notyet")["exp_R"])
        self.assertGreater(a1, c1)
        self.assertLess(a2, c2)
        # and the samples are real on both sides (no n=5 flip excuses)
        for r in (self._r("W1", "pdh_dayext_agree"),
                  self._r("W2", "pdh_dayext_agree"),
                  self._r("W1", "pdh_dayext_notyet"),
                  self._r("W2", "pdh_dayext_notyet")):
            self.assertGreaterEqual(r["trades"], 30)

    def test_ungated_pdh_is_the_only_replicated_arm(self):
        # pdh_w10_control beats the funnel on BOTH independent windows
        # (0.612 vs 0.524, 0.623 vs 0.521) at n=95/100 — the first arm in
        # the loop's history to replicate out-of-regime. Among the non-lane
        # arms it is the ONLY one that does.
        for w in ("W1", "W2"):
            self.assertGreater(self._r(w, "pdh_w10_control")["exp_R"],
                               self._r(w, "CURRENT_FUNNEL")["exp_R"], w)
            self.assertGreaterEqual(self._r(w, "pdh_w10_control")["trades"], 90)
        rep = self.v["replicated_in_both"]
        self.assertTrue(rep["pdh_w10_control"])
        for arm in ("pdh_dayext_agree", "pdh_dayext_agree_e25",
                    "pdh_dayext_notyet", "nr7_break_w10"):
            self.assertFalse(rep[arm], arm)

    def test_nr7_loses_both_independent_windows(self):
        # The contaminated-fresh lane champion (0.620 lane exp_R) scores
        # 0.437/0.390 standalone vs funnel 0.524/0.521 — it never beat the
        # funnel out-of-regime at all.
        for w in ("W1", "W2"):
            self.assertLess(self._r(w, "nr7_break_w10")["exp_R"],
                            self._r(w, "CURRENT_FUNNEL")["exp_R"], w)
            self.assertGreaterEqual(self._r(w, "nr7_break_w10")["trades"], 400)

    def test_gated_lane_replicates_only_a_marginal_positive(self):
        # lane_funnel_then_gated beats the funnel on both windows
        # (0.559/0.534 vs 0.524/0.521) — the first replicated-positive lane
        # — but the margin is < +0.05R/trade and DD is no better on W2;
        # b70 must weigh it as marginal, not as round 9's headline did.
        for w in ("W1", "W2"):
            lane, f = self._r(w, "lane_funnel_then_gated"), \
                self._r(w, "CURRENT_FUNNEL")
            self.assertGreater(lane["exp_R"], f["exp_R"], w)
            self.assertLess(lane["exp_R"] - f["exp_R"], 0.05, w)
            self.assertGreaterEqual(lane["trades"], f["trades"], w)
        self.assertTrue(self.v["replicated_in_both"]["lane_funnel_then_gated"])

    def test_cached_baseline_is_regime_specific(self):
        # The merit bar's 0.854 cached baseline vs the funnel's ~0.52 on
        # BOTH independent windows: the bar itself was inflated by the
        # July-August regime. Pin the gap so no future round can quote
        # 0.854 as "the funnel's expectancy".
        cached_funnel = 0.854
        for w in ("W1", "W2"):
            f = self._r(w, "CURRENT_FUNNEL")["exp_R"]
            self.assertLess(f, cached_funnel - 0.30, w)


class TestVerdictLogic(unittest.TestCase):
    """verdict() is the seed of b74's replication protocol — pin the rule
    itself on synthetic ledgers, not just its output on the shipped one."""

    @staticmethod
    def _led(f1, f2, arm1, arm2):
        # verdict() walks its full arm list; give every arm the pdh value so
        # only the pdh_w10_control row drives the assertion.
        others = {a: {"ladder_ts": {"exp_R": 0.0, "trades": 10}}
                  for a in ("pdh_dayext_agree", "pdh_dayext_agree_e25",
                            "pdh_dayext_notyet", "nr7_break_w10",
                            "lane_funnel_then_gated")}

        def win(f, a):
            row = {"CURRENT_FUNNEL": {"ladder_ts": {"exp_R": f, "trades": 300}},
                   "pdh_w10_control": {"ladder_ts": {"exp_R": a, "trades": 90}}}
            row.update(others)
            return row
        return {"W1": win(f1, arm1), "W2": win(f2, arm2)}

    def test_beats_both_windows_replicates(self):
        v = conf.verdict(self._led(0.5, 0.5, 0.6, 0.7))
        self.assertTrue(v["replicated_in_both"]["pdh_w10_control"])

    def test_beats_only_one_window_does_not(self):
        v = conf.verdict(self._led(0.5, 0.5, 0.9, 0.1))
        self.assertFalse(v["replicated_in_both"]["pdh_w10_control"])

    def test_zero_trade_arm_never_beats(self):
        # None exp_R (arm fired 0 trades — the b69/b71 dead-arm class) must
        # read as a FAIL, never as a missing-number pass.
        v = conf.verdict(self._led(0.5, 0.5, None, None))
        self.assertFalse(v["replicated_in_both"]["pdh_w10_control"])

    def test_tie_is_not_a_beat(self):
        v = conf.verdict(self._led(0.5, 0.5, 0.5, 0.6))
        self.assertFalse(v["replicated_in_both"]["pdh_w10_control"])


if __name__ == "__main__":
    unittest.main()
