"""b68 round 12 (b68m) — PDH x HTF-trend gate: integrity + verdict pins.

The round's claim (data/backtest/b68m_htf_pdh_confirm.json): gating the only
replicated geometry (pdh_w10, round 11) on an H4-trend STATE oracle is the
first arm in loop history to (a) beat the funnel on BOTH truly independent
windows, (b) beat its own ungated control on both, and (c) keep the
agree > complement ordering on both — the three conditions round 9's
dayext champion failed (it flipped sign between regimes).

Pinned from the SHIPPED JSONs (offline, deterministic):
1. b76 window integrity: the cached leg is LABELLED in-sample
   (_overlap_with_cached == 3000), W1/W2 carry 0 and the founding
   contamination fact is carried through.
2. The b71 harness contract on every arm row of all three legs (ladder_ts +
   hold columns, derived time exit 144, empty honesty complaints).
3. The gate is not vacuous and not an event in disguise: H1's gate_share is
   ~0.9 (nearly vacuous — recorded so nobody quotes H1 as "a filter"), H4's
   is 0.5-0.7 with a real disagree cut; the agree-subset state age proves
   the oracle is a slow STATE (median >= 5 H4 bars).
4. The verdict: pdh_h4t_agree replicated on both windows, beats the control
   on both, agree > disagree on both; the lane replicates only a MARGINAL
   positive (< +0.05R) — b70 must weigh it as marginal, not headline.
5. trend_state() itself, replayed on synthetic bars: no lookahead (mutating
   a FUTURE HTF bar cannot change the state at an earlier entry), warmup
   silence, and the EMA-slope direction on both sides.
6. Registry cross-consistency: b62_strategy_lab.json's round-12 rows carry
   the same cached exp_R as the lab ledger (the b68e convention).
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68m_htf_pdh_lab as mm      # noqa: E402
from scripts import b68m_htf_pdh_confirm as conf  # noqa: E402

LAB = os.path.join(ROOT, "data", "backtest", "b68m_htf_pdh_lab.json")
LEDGER = os.path.join(ROOT, "data", "backtest", "b68m_htf_pdh_confirm.json")
REGISTRY = os.path.join(ROOT, "data", "backtest", "b62_strategy_lab.json")

ARMS = ("CURRENT_FUNNEL", "pdh_w10_control", "pdh_h1t_agree",
        "pdh_h4t_agree", "pdh_h4t_disagree", "lane_funnel_then_h4pdh")
LEGS = ("cached", "W1", "W2")


def _load(path):
    with open(path) as f:
        return json.load(f)


class TestWindowIntegrityB76(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = _load(LEDGER)

    def test_cached_leg_is_labelled_in_sample(self):
        # b76 rule (c): a set that overlaps the training regime must be
        # LABELLED, never quotable as out-of-sample. The cached leg carries
        # its contamination openly.
        self.assertEqual(self.led["cached"]["_overlap_with_cached"], 3000)

    def test_independent_legs_have_zero_overlap(self):
        for w in ("W1", "W2"):
            self.assertEqual(self.led[w]["_overlap_with_cached"], 0, w)
            self.assertEqual(self.led[w]["_bars"], 6000, w)

    def test_founding_contamination_fact_carried(self):
        self.assertEqual(self.led["_last6000_overlap_with_cached"], 3000)

    def test_funnel_baseline_matches_round11_ledger(self):
        # Same bars, same harness, deterministic: round 12's funnel numbers
        # must BE round 11's, or one of the two ledgers drifted.
        r11 = _load(os.path.join(ROOT, "data", "backtest",
                                 "b68l_independent_confirm.json"))
        for w in ("W1", "W2"):
            self.assertEqual(
                self.led[w]["CURRENT_FUNNEL"]["ladder_ts"]["exp_R"],
                r11[w]["CURRENT_FUNNEL"]["ladder_ts"]["exp_R"], w)
            self.assertEqual(
                self.led[w]["pdh_w10_control"]["ladder_ts"]["exp_R"],
                r11[w]["pdh_w10_control"]["ladder_ts"]["exp_R"], w)


class TestHarnessContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = _load(LEDGER)

    def test_time_exit_derived_to_144_on_every_leg(self):
        for leg in LEGS:
            self.assertEqual(self.led[leg]["_time_stop_bars"], 144, leg)

    def test_every_arm_row_has_ladder_ts_and_hold_columns(self):
        for leg in LEGS:
            for arm in ARMS:
                row = self.led[leg][arm]
                self.assertIn("ladder_ts", row, f"{leg}/{arm}")
                for mode in ("plain", "ladder", "ladder_ts"):
                    s = row[mode]
                    for col in ("mean_hold_bars", "p95_hold_bars",
                                "max_hold_bars", "holds_over_time_exit"):
                        self.assertIsNotNone(s[col], f"{leg}/{arm}:{mode}.{col}")

    def test_every_leg_passed_its_own_honesty_gate(self):
        for leg in LEGS:
            self.assertEqual(self.led[leg]["_honesty_complaints"], [], leg)


class TestGateAntiVacuity(unittest.TestCase):
    """A combination whose gate fires on ~100% is the same arm twice (b72)."""

    @classmethod
    def setUpClass(cls):
        cls.led = _load(LEDGER)

    def test_h1_gate_is_nearly_vacuous_and_recorded_as_such(self):
        # H1 trend agrees with ~90% of pdh breaks on every leg — measured,
        # not assumed. If this ever drops below 0.8 the "H1 is not a filter"
        # premise in the round's write-up must be re-checked, not silently
        # reused.
        for leg in LEGS:
            p = self.led[leg]["_probe"]["h1"]
            self.assertGreaterEqual(p["gate_share"], 0.80, leg)
            self.assertLessEqual(p["cut_share"], 0.05, leg)

    def test_h4_gate_is_a_real_filter_on_every_leg(self):
        for leg in LEGS:
            p = self.led[leg]["_probe"]["h4"]
            self.assertGreaterEqual(p["gate_share"], 0.45, leg)
            self.assertLessEqual(p["gate_share"], 0.70, leg)
            self.assertGreaterEqual(p["disagree"], 11, leg)

    def test_oracle_is_a_state_not_an_event(self):
        # b75 rule-(6) probe for a STATE oracle: the agree-subset's state
        # age in HTF bars. A median of 1-2 would mean the gate is really an
        # event trigger (round-10's chase-tax shape); >=5 H4 bars (>=20h)
        # means it is background regime.
        for leg in LEGS:
            p = self.led[leg]["_probe"]["h4"]
            self.assertGreaterEqual(
                p["agree_state_age_median_htf_bars"], 5, leg)


class TestShippedVerdicts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = _load(LEDGER)
        cls.v = cls.led["_verdict"]

    def _r(self, w, arm):
        return self.led[w][arm]["ladder_ts"]

    def test_h4_gated_pdh_replicates_on_both_independent_windows(self):
        # THE round's headline: 0.657 W1 / 0.927 W2 vs funnel 0.524/0.521,
        # n=55/63. First arm to satisfy all three replication conditions.
        for w in ("W1", "W2"):
            self.assertGreater(self._r(w, "pdh_h4t_agree")["exp_R"],
                               self._r(w, "CURRENT_FUNNEL")["exp_R"], w)
            self.assertGreaterEqual(self._r(w, "pdh_h4t_agree")["trades"], 50)
        self.assertTrue(self.v["replicated_in_both"]["pdh_h4t_agree"])

    def test_gate_lifts_its_own_control_on_both_windows(self):
        # Same-bars control (round-11's replicated pdh_w10): the gate must
        # beat IT, not just the funnel, or the lift is just "pdh again".
        for w in ("W1", "W2"):
            self.assertGreater(self._r(w, "pdh_h4t_agree")["exp_R"],
                               self._r(w, "pdh_w10_control")["exp_R"], w)

    def test_selection_ordering_holds_out_of_regime(self):
        # agree > disagree on BOTH independent windows — the check round 9's
        # dayext gate failed (it flipped sign). Samples real on both sides.
        for w in ("W1", "W2"):
            self.assertGreater(self._r(w, "pdh_h4t_agree")["exp_R"],
                               self._r(w, "pdh_h4t_disagree")["exp_R"], w)
            self.assertGreaterEqual(self._r(w, "pdh_h4t_disagree")["trades"],
                                    20, w)

    def test_cached_selection_flips_and_is_disclosed(self):
        # Honest disclosure of the round's awkward number: on the IN-SAMPLE
        # cached leg the disagree cut (1.237, n=11) beats the gated arm
        # (0.641). The cached regime is exactly what b76 says cannot be
        # trusted; the out-of-regime legs are the decision. Pin it so the
        # write-up can never quietly drop this row.
        self.assertGreater(self._r("cached", "pdh_h4t_disagree")["exp_R"],
                           self._r("cached", "pdh_h4t_agree")["exp_R"])
        self.assertLess(self._r("cached", "pdh_h4t_disagree")["trades"], 15)

    def test_h1_gate_lifts_only_marginally(self):
        # H1 agree beats the control on both windows but by < +0.10R —
        # consistent with a ~90% gate being mostly the control itself.
        for w in ("W1", "W2"):
            d = (self._r(w, "pdh_h1t_agree")["exp_R"]
                 - self._r(w, "pdh_w10_control")["exp_R"])
            self.assertGreaterEqual(d, 0.0, w)
            self.assertLess(d, 0.10, w)

    def test_lane_replicates_only_a_marginal_positive(self):
        # b70 input: the H4-gated lane beats the funnel on both windows but
        # by < +0.05R/trade — the same marginal shape as round 11's gated
        # lane, NOT round 9's contaminated headline.
        for w in ("W1", "W2"):
            lane, f = self._r(w, "lane_funnel_then_h4pdh"), \
                self._r(w, "CURRENT_FUNNEL")
            self.assertGreater(lane["exp_R"], f["exp_R"], w)
            self.assertLess(lane["exp_R"] - f["exp_R"], 0.05, w)
        self.assertTrue(self.v["replicated_in_both"]["lane_funnel_then_h4pdh"])

    def test_stretch_probe_shows_no_chase_tax_on_two_of_three_legs(self):
        # b73 rule (b): gated mean stretch should not exceed control by more
        # than 0.10 ATR on any leg (round 10's failure mode was 4.0 vs 0.56).
        for leg in LEGS:
            sp = self.led[leg]["_stretch_probe_h4"]
            self.assertLessEqual(sp["gated"]["mean_stretch_atr"]
                                 - sp["control"]["mean_stretch_atr"],
                                 0.10, leg)


class TestTrendStateLogic(unittest.TestCase):
    """trend_state() replayed on synthetic bars — the oracle's contract."""

    @staticmethod
    def _mk_htf(closes, start=0, span=3600):
        rows = [{"time": start + n * span, "close": c}
                for n, c in enumerate(closes)]
        return mm._htf_prep(rows, span)

    def test_uptrend_and_downtrend_detected(self):
        up = self._mk_htf([100 + n for n in range(80)])
        dn = self._mk_htf([300 - n for n in range(80)])
        entry = up["t"][-1] + up["span"]          # bar after the last close
        self.assertEqual(mm.trend_state(up, entry)[0], "BUY")
        self.assertEqual(mm.trend_state(dn, entry)[0], "SELL")

    def test_warmup_is_silent(self):
        prep = self._mk_htf([100 + n for n in range(20)])
        side, _ = mm.trend_state(prep, prep["t"][-1] + prep["span"])
        self.assertIsNone(side)

    def test_no_lookahead_future_bars_cannot_change_the_state(self):
        prep = self._mk_htf([100 + n for n in range(80)])
        entry = prep["t"][-1] + prep["span"]
        before = mm.trend_state(prep, entry)
        # append 30 FUTURE bars that reverse the trend hard
        rows = [{"time": r["time"], "close": c} for r, c in
                zip([{"time": prep["t"][n]} for n in range(80)],
                    [100 + n for n in range(80)])]
        for n in range(30):
            rows.append({"time": entry + n * 3600, "close": 50 - n * 10})
        prep2 = mm._htf_prep(rows, 3600)
        self.assertEqual(mm.trend_state(prep2, entry), before)

    def test_only_fully_closed_htf_bars_are_read(self):
        # An H1 bar that OPENS before entry but closes AFTER it must not
        # count. The last bar closes 200 points BELOW its EMA — if the state
        # read that open bar it would go None/SELL; reading only closed bars
        # it stays BUY.
        closes = [100 + n for n in range(79)] + [100 + 78 - 200]
        prep = self._mk_htf(closes)
        mid_last = prep["t"][-1] + 1800           # last H1 bar still open
        side, _ = mm.trend_state(prep, mid_last)
        self.assertEqual(side, "BUY")
        # one bar later the spike bar IS closed and must flip the state
        side_after, _ = mm.trend_state(prep, prep["t"][-1] + prep["span"] + 1)
        self.assertNotEqual(side_after, "BUY")


class TestVerdictLogic(unittest.TestCase):
    """verdict()'s replication rule replayed on synthetic ledgers."""

    @staticmethod
    def _led(f1, f2, a1, a2):
        others = {a: {"ladder_ts": {"exp_R": 0.0, "trades": 10}}
                  for a in ("pdh_h1t_agree", "pdh_h4t_disagree",
                            "lane_funnel_then_h4pdh")}

        def win(f, a):
            row = {"CURRENT_FUNNEL": {"ladder_ts": {"exp_R": f, "trades": 300}},
                   "pdh_w10_control": {"ladder_ts": {"exp_R": 0.0, "trades": 90}},
                   "pdh_h4t_agree": {"ladder_ts": {"exp_R": a, "trades": 60}}}
            row.update(others)
            return row
        return {"W1": win(f1, a1), "W2": win(f2, a2)}

    def test_pass_requires_both_windows(self):
        v = conf.verdict(self._led(0.52, 0.52, 0.60, 0.40))
        self.assertFalse(v["replicated_in_both"]["pdh_h4t_agree"])
        v = conf.verdict(self._led(0.52, 0.52, 0.60, 0.60))
        self.assertTrue(v["replicated_in_both"]["pdh_h4t_agree"])

    def test_none_and_tie_never_beat(self):
        v = conf.verdict(self._led(0.52, 0.52, None, 0.52))
        self.assertFalse(v["W1"]["pdh_h4t_agree"]["beats_funnel"])
        self.assertFalse(v["W2"]["pdh_h4t_agree"]["beats_funnel"])
        self.assertFalse(v["replicated_in_both"]["pdh_h4t_agree"])


class TestRegistryCrossConsistency(unittest.TestCase):
    def test_round12_rows_match_the_lab_ledger(self):
        reg = {r["name"]: r for r in _load(REGISTRY)}
        lab = _load(LAB)
        for name in ("pdh_h4t_agree", "pdh_h4t_disagree",
                     "lane_funnel_then_h4pdh"):
            self.assertIn(name, reg, name)
            r = reg[name]
            for key in ("w1_exp_R", "w2_exp_R", "funnel_w1_exp_R",
                        "funnel_w2_exp_R", "verdict"):
                self.assertIn(key, r, f"{name}.{key}")
        # the registry's cached numbers must BE the lab ledger's
        self.assertEqual(reg["pdh_h4t_agree"]["exp_R"],
                         lab["pdh_h4t_agree"]["ladder_ts"]["exp_R"])
        self.assertEqual(reg["pdh_h4t_agree"]["trades"],
                         lab["pdh_h4t_agree"]["ladder_ts"]["trades"])
        # merit-bar discipline: nothing wired, replication is the claim
        self.assertIn("NOT wired", reg["pdh_h4t_agree"]["verdict"])


if __name__ == "__main__":
    unittest.main()
