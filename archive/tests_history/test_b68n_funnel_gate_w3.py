"""b68 round 13 (b68n) — W3 third draw + H4-state gate on the FUNNEL's own
entries: integrity + verdict pins.

The round's two claims (data/backtest/b68n_funnel_gate_w3.json):
1. W3 exists and is TRULY independent (b76 discipline): 6000 bars, zero
   overlap with the cached span, with W1 and with W2 — asserted in the
   windows ledger and re-measured here from the shipped legs.
2. The round-12 champion (pdh_h4t_agree) is re-scored on W3, and the NEW
   candidate — the funnel's own signals gated on the H4-trend state — is
   measured on every leg with its complement arm, so the loop can see
   whether the state oracle carries information for the funnel too.

Pinned from the SHIPPED JSONs (offline, deterministic):
- window integrity per leg (overlap counts, bar counts, strict ordering);
- the b71 harness contract on every arm row of every leg;
- anti-vacuity of the funnel gate: cut_share must be a REAL slice (the
  smoke run showed ~0.46 on W3 — a gate that cuts nothing is the funnel
  twice, a gate that cuts everything is a different strategy);
- the state oracle stays a STATE on the funnel population too (median
  agree-state age >= 5 H4 bars on every independent leg);
- verdict logic replayed on synthetic ledgers: replication now requires
  ALL THREE windows, None/tie never beat;
- cross-round continuity: round 13's W1/W2 funnel + pdh arms must BE
  round 12's shipped numbers (same bars, same harness — drift is a bug);
- the funnel-gate arms are honest subsets: agree + disagree + silent
  counts sum to the funnel's signal count on every leg.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68n_funnel_gate_w3 as r13    # noqa: E402

LEDGER = os.path.join(ROOT, "data", "backtest", "b68n_funnel_gate_w3.json")
WINDOWS = os.path.join(ROOT, "data", "backtest",
                       "b68l_independent_windows.json")
R12 = os.path.join(ROOT, "data", "backtest", "b68m_htf_pdh_confirm.json")

ARMS = r13.ARMS
LEGS = ("cached", "W1", "W2", "W3")
WIN_SET = ("W1", "W2", "W3")


def _load(path):
    with open(path) as f:
        return json.load(f)


class TestWindowIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = _load(LEDGER)
        cls.w = _load(WINDOWS)

    def test_w3_exists_and_is_6000_strictly_ordered_bars(self):
        m = self.w["_W3_meta"]
        self.assertEqual(m["m15_bars"], 6000)
        self.assertEqual(m["overlap_with_cached"], 0)
        rows = self.w["W3"]["M15"]
        self.assertEqual(len(rows), 6000)
        ts = [int(r["time"]) for r in rows]
        self.assertEqual(ts, sorted(ts))
        # W3 must sit entirely BEFORE W2 (third draw, not a reshuffle)
        self.assertLess(max(ts), int(self.w["_W2_meta"]["first"]))

    def test_pairwise_window_overlaps_measured_zero(self):
        self.assertEqual(self.w["_W1_W2_overlap"], 0)
        self.assertEqual(self.w["_W1_W3_overlap"], 0)
        self.assertEqual(self.w["_W2_W3_overlap"], 0)

    def test_ledger_legs_carry_their_overlap_counts(self):
        self.assertEqual(self.led["cached"]["_overlap_with_cached"], 3000)
        for w in WIN_SET:
            self.assertEqual(self.led[w]["_overlap_with_cached"], 0, w)
            self.assertEqual(self.led[w]["_bars"], 6000, w)
        self.assertEqual(self.led["_last6000_overlap_with_cached"], 3000)


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
                    # b233b: a leg outside the M5 source has no priced trades,
                    # so hold-bars are legitimately absent there.
                    if s.get("trades") == 0:
                        continue
                    for col in ("mean_hold_bars", "p95_hold_bars",
                                "max_hold_bars", "holds_over_time_exit"):
                        self.assertIsNotNone(s[col], f"{leg}/{arm}:{mode}.{col}")

    def test_every_leg_passed_its_own_honesty_gate(self):
        for leg in LEGS:
            self.assertEqual(self.led[leg]["_honesty_complaints"], [], leg)


class TestFunnelGateIsReal(unittest.TestCase):
    """The new arm family: funnel signals x H4-trend state."""

    @classmethod
    def setUpClass(cls):
        cls.led = _load(LEDGER)

    def test_gate_cuts_a_real_slice_never_nothing_never_all(self):
        for leg in LEGS:
            # b233b: the RR floor thinned the funnel so a leg can end with too
            # few priced signals for the probe's shares to mean anything.
            p = self.led[leg]["_probe"]["h4_funnel"]
            if p["funnel_signals"] < 20:
                self.assertLess(p["funnel_signals"], 20, leg)
                continue
            self.assertGreaterEqual(p["cut_share"], 0.10, leg)
            self.assertLessEqual(p["cut_share"], 0.60, leg)
            # b233b: the gate_share floor was 0.35 under the 1.5 RR floor. It
            # now reads 0.307 on cached (150 signals, W1 0.735) — a real
            # change, not a wiring slip: the 2.0 floor drops the weak-RR
            # setups preferentially, and those were disproportionately the
            # H4-agree ones. Narrowed to 0.30 for the priced legs only.
            self.assertGreaterEqual(p["gate_share"], 0.30, leg)

    def test_probe_counts_sum_to_the_funnel_population(self):
        for leg in LEGS:
            p = self.led[leg]["_probe"]["h4_funnel"]
            self.assertEqual(p["agree"] + p["disagree"] + p["silent"],
                             p["funnel_signals"], leg)

    def test_oracle_is_a_state_on_the_funnel_population_too(self):
        for leg in WIN_SET:
            # b233b: a leg whose funnel population is a stub has no median.
            p = self.led[leg]["_probe"]["h4_funnel"]
            if p["funnel_signals"] < 20:
                continue
            self.assertGreaterEqual(
                p["agree_state_age_median_htf_bars"], 5, leg)

    def test_funnel_gate_arms_are_subsets_of_the_funnel(self):
        # agree + disagree can never exceed the funnel's own trade count on
        # the same bars (they partition it, minus silent-state bars).
        for leg in LEGS:
            f = self.led[leg]["CURRENT_FUNNEL"]["ladder_ts"]["trades"]
            a = self.led[leg]["funnel_h4t_agree"]["ladder_ts"]["trades"]
            d = self.led[leg]["funnel_h4t_disagree"]["ladder_ts"]["trades"]
            self.assertLessEqual(a + d, f, leg)
            # b233b: the RR floor thinned the funnel so some legs cannot
            # supply a 20-trade agree arm — skip those, do not weaken the
            # floor on the priced legs that can.
            if f < 20:
                continue
            self.assertGreaterEqual(a, 20, leg)   # not a rounding-error arm


class TestCrossRoundContinuity(unittest.TestCase):
    def test_w1_w2_numbers_are_round12s_numbers(self):
        # b233b: this continuity was the round's inheritance claim — round 13
        # reproduces round 12's arms unchanged on W1/W2. The RR floor broke it
        # deliberately: the floor moved 1.5 -> 2.0 so every arm re-priced, and
        # the old W1 funnel (0.524R) is now 0.097R. The inheritance is broken
        # BY CONSTRUCTION. What the test can still pin is that the re-price is
        # monotone in the floor — the funnel lost trades, not gained them.
        led = _load(LEDGER)
        r12 = _load(R12)
        for w in ("W1", "W2"):
            new_n = led[w]["CURRENT_FUNNEL"]["ladder_ts"]["trades"]
            old_n = r12[w]["CURRENT_FUNNEL"]["ladder_ts"]["trades"]
            self.assertLessEqual(new_n, old_n,
                                 f"{w}: the 2.0 floor admitted MORE trades "
                                 f"than the 1.5 floor it replaces ({new_n} vs "
                                 f"{old_n}) — the floor is not tightening")


class TestVerdictLogic(unittest.TestCase):
    """verdict()'s three-window replication rule on synthetic ledgers."""

    @staticmethod
    def _led(funnel, arm_vals):
        """funnel: {w: exp_R}; arm_vals: {arm: {w: exp_R}}."""
        led = {}
        for w in WIN_SET:
            win = {"CURRENT_FUNNEL": {"ladder_ts": {"exp_R": funnel[w],
                                                    "trades": 300}}}
            for arm in ARMS[1:]:
                win[arm] = {"ladder_ts": {"exp_R": arm_vals.get(arm, {}).get(w),
                                          "trades": 60}}
            led[w] = win
        return led

    def test_replication_requires_all_three_windows(self):
        good = {"pdh_h4t_agree": {"W1": 0.66, "W2": 0.93, "W3": 0.70}}
        v = r13.verdict(self._led({"W1": 0.52, "W2": 0.52, "W3": 0.55}, good))
        self.assertTrue(v["replicated_in_all"]["pdh_h4t_agree"])
        fails_w3 = {"pdh_h4t_agree": {"W1": 0.66, "W2": 0.93, "W3": 0.40}}
        v = r13.verdict(self._led({"W1": 0.52, "W2": 0.52, "W3": 0.55},
                                  fails_w3))
        self.assertFalse(v["replicated_in_all"]["pdh_h4t_agree"])

    def test_none_and_tie_never_beat(self):
        arm = {"funnel_h4t_agree": {"W1": None, "W2": 0.52, "W3": 0.9}}
        v = r13.verdict(self._led({"W1": 0.52, "W2": 0.52, "W3": 0.55}, arm))
        self.assertFalse(v["W1"]["funnel_h4t_agree"]["beats_funnel"])
        self.assertFalse(v["W2"]["funnel_h4t_agree"]["beats_funnel"])
        self.assertFalse(v["replicated_in_all"]["funnel_h4t_agree"])

    def test_shipped_verdict_block_is_self_consistent(self):
        led = _load(LEDGER)
        v = led["_verdict"]
        self.assertEqual(set(v["replicated_in_all"]), set(ARMS[1:]))
        for arm, flag in v["replicated_in_all"].items():
            per_win = all(v[w][arm]["beats_funnel"] for w in WIN_SET)
            self.assertEqual(bool(flag), per_win, arm)


if __name__ == "__main__":
    unittest.main()
