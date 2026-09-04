"""b68 round 14 (b68n4) — the FOURTH DRAW: does funnel_h4t_agree survive W4?

Round 13 left the loop's best candidate (the funnel's own signals gated on
the H4-trend state, the first arm to beat the funnel on all three
independent windows) with a warning: margins +0.093/+0.032/+0.008 in
window order. This round spends b74's fourth draw (W4 = 2025-07-09 →
2025-10-08, zero overlap asserted) and the shipped ledger
(data/backtest/b68n4_fourth_draw.json) answers: DIES — 0.517 vs funnel
0.532 on the SAME W4 bars.

Pinned from the SHIPPED JSONs (offline, deterministic):
- W4 window integrity (b76 discipline): 6000 bars, zero overlap with the
  cached span and with W1/W2/W3, strictly older than W3;
- the b71 harness contract on every W4 arm row + the leg's own honesty
  gate + the zero-overlap fact recorded in the leg;
- cross-round continuity: the W1/W2/W3 legs are byte-identical to round
  13's shipped ledger (same bars, same harness — drift is a bug);
- the verdict block: DIES with the exact margin series, and the series
  read CHRONOLOGICALLY (W4 oldest → W1 newest) is monotonic INCREASING —
  the candidate's edge is a property of the RECENT regime, not a stable
  property of gold M15 (the round's headline finding, pinned as a fact);
- verdict()'s decision rule on synthetic ledgers: SURVIVES needs both
  the W4 beat AND the agree>cut ordering; None never beats;
- anti-vacuity of the W4 funnel-gate probe (cut_share >= 0.05, agree
  >= 20 trades — the gate is a real slice, not a rounding error) and the
  state-age check (b75 rule 6: the oracle stays a slow STATE on W4 too);
- the registry row for funnel_h4t_agree carries the four-window numbers
  and the NOT-wired discipline.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68n4_fourth_draw as r14      # noqa: E402

LEDGER = os.path.join(ROOT, "data", "backtest", "b68n4_fourth_draw.json")
WINDOWS = os.path.join(ROOT, "data", "backtest",
                       "b68l_independent_windows.json")
R13 = os.path.join(ROOT, "data", "backtest", "b68n_funnel_gate_w3.json")
REGISTRY = os.path.join(ROOT, "data", "backtest", "b62_strategy_lab.json")

ARMS = r14.ARMS
W4 = "W4"


def _load(path):
    with open(path) as f:
        return json.load(f)


class TestW4Integrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = _load(WINDOWS)

    def test_w4_is_6000_strictly_ordered_bars_zero_cached_overlap(self):
        m = self.w["_W4_meta"]
        self.assertEqual(m["m15_bars"], 6000)
        self.assertEqual(m["overlap_with_cached"], 0)
        rows = self.w["W4"]["M15"]
        self.assertEqual(len(rows), 6000)
        ts = [int(r["time"]) for r in rows]
        self.assertEqual(ts, sorted(ts))

    def test_w4_sits_entirely_before_w3(self):
        ts = [int(r["time"]) for r in self.w["W4"]["M15"]]
        self.assertLess(max(ts), int(self.w["_W3_meta"]["first"]))

    def test_all_pairwise_overlaps_including_w4_measured_zero(self):
        for k in ("_W1_W2_overlap", "_W1_W3_overlap", "_W1_W4_overlap",
                  "_W2_W3_overlap", "_W2_W4_overlap", "_W3_W4_overlap"):
            self.assertEqual(self.w[k], 0, k)


class TestLedgerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = _load(LEDGER)

    def test_w4_leg_records_its_own_facts(self):
        win = self.led[W4]
        self.assertEqual(win["_overlap_with_cached"], 0)
        self.assertEqual(win["_bars"], 6000)
        self.assertEqual(win["_time_stop_bars"], 144)
        self.assertEqual(win["_honesty_complaints"], [])

    def test_every_w4_arm_row_has_ladder_ts_and_hold_columns(self):
        for arm in ARMS:
            row = self.led[W4][arm]
            self.assertIn("ladder_ts", row, arm)
            for mode in ("plain", "ladder", "ladder_ts"):
                s = row[mode]
                for col in ("mean_hold_bars", "p95_hold_bars",
                            "max_hold_bars", "holds_over_time_exit"):
                    self.assertIsNotNone(s[col], f"W4/{arm}:{mode}.{col}")

    def test_w1_w2_w3_legs_are_round13s_legs_unchanged(self):
        r13 = _load(R13)
        for w in ("W1", "W2", "W3"):
            for arm in ARMS:
                self.assertEqual(
                    self.led[w][arm]["ladder_ts"]["exp_R"],
                    r13[w][arm]["ladder_ts"]["exp_R"], f"{w}/{arm}")
                self.assertEqual(
                    self.led[w][arm]["ladder_ts"]["trades"],
                    r13[w][arm]["ladder_ts"]["trades"], f"{w}/{arm}")


class TestFourthDrawVerdict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = _load(LEDGER)
        cls.v = cls.led["_verdict"]

    def test_candidate_dies_on_w4(self):
        # THE round's headline: funnel_h4t_agree 0.517 (n=267) vs funnel
        # 0.532 (n=340) on the SAME W4 bars — the all-window streak breaks.
        self.assertFalse(self.v["beats_funnel_W4"])
        self.assertEqual(self.v["verdict"], "DIES")
        self.assertEqual(self.v["W4_agree_exp_R"], 0.517)
        self.assertEqual(self.v["W4_funnel_exp_R"], 0.532)
        self.assertEqual(self.v["W4_agree_n"], 267)
        self.assertEqual(self.v["W4_funnel_n"], 340)

    def test_margin_series_exact_and_chronologically_monotonic(self):
        m = self.v["margin_series"]
        self.assertEqual(m, {"W1": 0.093, "W2": 0.032, "W3": 0.008,
                             "W4": -0.015})
        # Read in TIME order (W4 oldest -> W1 newest) the margin GROWS
        # monotonically: the gate's edge is a property of the RECENT
        # regime, not a stable property of gold M15. Pinning the ordering
        # so a future round cannot quietly re-sell it as regime-free.
        chrono = [m["W4"], m["W3"], m["W2"], m["W1"]]
        self.assertEqual(chrono, sorted(chrono))

    def test_selection_ordering_holds_on_w4_despite_the_loss(self):
        # agree 0.517 > cut 0.445 on W4 — the flip was a W3/cached
        # phenomenon; the honest read is that BOTH properties (beat and
        # ordering) must hold, and only the beat fails here.
        self.assertTrue(self.v["ordering_holds_W4"])
        self.assertGreater(self.v["W4_agree_exp_R"], self.v["W4_cut_exp_R"])

    def test_champion_continuity_rows_on_w4(self):
        # pdh_h4t_agree BEATS the funnel on W4 (0.597 vs 0.532, n=82) —
        # it is 3-of-4 windows (failed W3). Pinned so the write-up cannot
        # cherry-pick either direction.
        w = self.led[W4]
        self.assertGreater(w["pdh_h4t_agree"]["ladder_ts"]["exp_R"],
                           w["CURRENT_FUNNEL"]["ladder_ts"]["exp_R"])
        self.assertLess(self.led["W3"]["pdh_h4t_agree"]["ladder_ts"]["exp_R"],
                        self.led["W3"]["CURRENT_FUNNEL"]["ladder_ts"]["exp_R"])

    def test_lane_still_positive_on_w4_but_not_promotable(self):
        w = self.led[W4]
        self.assertGreater(w["lane_funnel_then_h4pdh"]["ladder_ts"]["exp_R"],
                           w["CURRENT_FUNNEL"]["ladder_ts"]["exp_R"])


class TestProbeAntiVacuity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = _load(LEDGER)[W4]["_probe"]["h4_funnel"]

    def test_gate_cuts_a_real_slice_on_w4(self):
        self.assertGreaterEqual(self.p["cut_share"], 0.05)
        self.assertGreaterEqual(self.p["gate_share"], 0.35)
        self.assertGreaterEqual(self.p["disagree"], 20)

    def test_probe_counts_partition_the_funnel_population(self):
        self.assertEqual(self.p["agree"] + self.p["disagree"]
                         + self.p["silent"], self.p["funnel_signals"])

    def test_oracle_is_a_state_on_w4_too(self):
        self.assertGreaterEqual(self.p["agree_state_age_median_htf_bars"], 5)

    def test_funnel_gate_arms_are_subsets(self):
        led = _load(LEDGER)
        f = led[W4]["CURRENT_FUNNEL"]["ladder_ts"]["trades"]
        a = led[W4]["funnel_h4t_agree"]["ladder_ts"]["trades"]
        d = led[W4]["funnel_h4t_disagree"]["ladder_ts"]["trades"]
        self.assertLessEqual(a + d, f)
        self.assertGreaterEqual(a, 20)


class TestVerdictRuleSynthetic(unittest.TestCase):
    """verdict()'s three-way rule on hand-built W4 rows."""

    @staticmethod
    def _led(f, a, c):
        """Full-shaped ledger: W1-W3 carry dummy funnel/agree/cut rows
        (only W4 drives the verdict; the margin series just needs the
        keys to exist)."""
        def win(fv, av, cv):
            return {"CURRENT_FUNNEL": {"ladder_ts": {"exp_R": fv,
                                                     "trades": 300}},
                    "funnel_h4t_agree": {"ladder_ts": {"exp_R": av,
                                                       "trades": 200}},
                    "funnel_h4t_disagree": {"ladder_ts": {"exp_R": cv,
                                                          "trades": 60}}}
        return {"W1": win(0.52, 0.61, 0.26), "W2": win(0.52, 0.55, 0.49),
                "W3": win(0.53, 0.54, 0.55), W4: win(f, a, c)}

    def test_survives_needs_beat_and_ordering(self):
        self.assertEqual(r14.verdict(self._led(0.53, 0.60, 0.40))["verdict"],
                         "SURVIVES")
        self.assertEqual(r14.verdict(self._led(0.53, 0.60, 0.61))["verdict"],
                         "DECAYS_OUT")
        self.assertEqual(r14.verdict(self._led(0.53, 0.50, 0.40))["verdict"],
                         "DIES")

    def test_none_never_beats(self):
        v = r14.verdict(self._led(0.53, None, 0.40))
        self.assertFalse(v["beats_funnel_W4"])
        self.assertEqual(v["verdict"], "DIES")

    def test_tie_never_beats(self):
        self.assertEqual(r14.verdict(self._led(0.53, 0.53, 0.40))["verdict"],
                         "DIES")


class TestRegistryRow(unittest.TestCase):
    def test_funnel_gate_row_carries_four_windows_and_discipline(self):
        reg = {r["name"]: r for r in _load(REGISTRY)}
        self.assertIn("funnel_h4t_agree", reg)
        r = reg["funnel_h4t_agree"]
        for key in ("w1_exp_R", "w2_exp_R", "w3_exp_R", "w4_exp_R",
                    "funnel_w4_exp_R", "verdict"):
            self.assertIn(key, r, f"funnel_h4t_agree.{key}")
        self.assertEqual(r["w4_exp_R"], 0.517)
        self.assertEqual(r["funnel_w4_exp_R"], 0.532)
        self.assertIn("NOT wired", r["verdict"])


if __name__ == "__main__":
    unittest.main()
