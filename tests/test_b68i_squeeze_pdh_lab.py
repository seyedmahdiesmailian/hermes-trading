"""b68 round 8 (PDH x NR7-squeeze combination lab) — integrity pins.

Built on the b71 harness and the b72 combination playbook, so the pins cover:

1. combo() is a PURE INTERSECTION: geometry comes from pdh_break unchanged;
   the squeeze oracle is direction-only. Disagreement or a silent oracle must
   return None, agreement must return the pdh dict byte-identical (the
   b69/round-6 stop-geometry trap class).
2. squeeze_dir() has NO LOOKAHEAD: it may only read bars <= i-2. Mutating the
   signal bar (i-1) and the entry bar (i) must not change the oracle's answer.
3. Anti-vacuity from the SHIPPED cached JSON: the gate must actually filter
   (gate_share well under 1) and must NOT be the same arm twice (agree and
   disagree both meaningfully > 0).
4. The b71 contract on both shipped ledgers: ladder_ts + hold columns on
   every arm row, honesty summary empty, and the CONTROL arm reproducing
   round 4's cached number (0.627R n=54) — if the harness or rebind changed
   the measurement this breaks.
5. The fresh confirm's verdict numbers (funnel 0.590 vs gated 0.603 vs
   control 0.609; the gated lane adds ~zero tot_R while the ungated lane
   doubles DD) so nobody re-quotes one set without the other.
6. rebind() repoints ALL ingredient modules AND rebuilds the day LEVELS from
   the new bars — trading fresh bars against cached-set levels would be the
   worst possible lab bug (round 4 rebuilt LEVELS by hand in the confirm;
   this round the rebuild lives in rebind itself, pinned here).
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68i_squeeze_pdh_lab as lab  # noqa: E402
from scripts import b68e_pdh_lab as pl           # noqa: E402
from scripts import b68f_nr7_lab as nl           # noqa: E402

LEDGER = os.path.join(ROOT, "data", "backtest", "b68i_squeeze_pdh_lab.json")
CONFIRM = os.path.join(ROOT, "data", "backtest",
                       "b68i_squeeze_pdh_confirm.json")
ARMS = ("pdh_w10_control", "pdh_squeeze_agree_k6", "pdh_squeeze_agree_k8")


def _load(path):
    with open(path) as f:
        return json.load(f)


class TestComboIsPureIntersection(unittest.TestCase):
    def setUp(self):
        self.saved = (lab.pl.pdh_break, lab.squeeze_dir)

    def tearDown(self):
        lab.pl.pdh_break, lab.squeeze_dir = self.saved

    def test_agreement_returns_the_pdh_dict_unchanged(self):
        sp = {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 102.0,
              "style": "pdh_break", "grade": "B"}
        lab.pl.pdh_break = lambda i, s=1.0: sp
        lab.squeeze_dir = lambda i, k: "BUY"
        self.assertIs(lab.combo(50, 6), sp)   # same object — zero mutation

    def test_disagreement_is_dropped(self):
        sp = {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 102.0}
        lab.pl.pdh_break = lambda i, s=1.0: sp
        lab.squeeze_dir = lambda i, k: "SELL"
        self.assertIsNone(lab.combo(50, 6))

    def test_silent_oracle_is_dropped(self):
        sp = {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 102.0}
        lab.pl.pdh_break = lambda i, s=1.0: sp
        lab.squeeze_dir = lambda i, k: None
        self.assertIsNone(lab.combo(50, 6))

    def test_no_pdh_signal_short_circuits_the_oracle(self):
        called = []
        lab.pl.pdh_break = lambda i, s=1.0: None
        lab.squeeze_dir = lambda i, k: (called.append(i) or "BUY")
        self.assertIsNone(lab.combo(50, 6))
        self.assertEqual(called, [])   # oracle never consulted — pure AND


class TestSqueezeOracleNoLookahead(unittest.TestCase):
    def test_oracle_reads_only_bars_up_to_i_minus_2(self):
        """Mutating the signal bar (i-1) and the entry bar (i) must not
        change squeeze_dir(i, k) — the oracle's window ends at i-2."""
        rows = lab.M15
        i = 200
        base = lab.squeeze_dir(i, lab.K6)
        saved = [{k: rows[t][k] for k in ("open", "high", "low", "close")}
                 for t in (i - 1, i)]
        try:
            for t in (i - 1, i):
                rows[t]["open"] = 1e6
                rows[t]["high"] = 1e6 + 1
                rows[t]["low"] = 1e6 - 1
                rows[t]["close"] = 1e6 + 0.5
            self.assertEqual(lab.squeeze_dir(i, lab.K6), base)
        finally:
            for t, s in zip((i - 1, i), saved):
                rows[t].update(s)
            self.assertEqual(lab.squeeze_dir(i, lab.K6), base)

    def test_oracle_direction_matches_a_real_resolved_squeeze(self):
        """Synthetic: NR7 bar, then a close ABOVE its high, then quiet bars.
        squeeze_dir must say BUY; a close BELOW must say SELL."""
        saved = (lab.M15, lab.IDX, nl.M15, nl.IDX)
        try:
            rows = [{"time": 1784109600 + 900 * n, "open": 100.0,
                     "high": 100.2, "low": 99.8, "close": 100.0}
                    for n in range(40)]
            lab.rebind(rows)
            # bar 20 is the NR7 (identical ranges make it the narrowest tie);
            # bar 30 closes above its high -> resolved BUY at i=33 (window 6
            # reaches back to j=27... so put the NR7 at 28 and resolve at 30)
            rows[28].update({"high": 100.05, "low": 99.95})
            rows[30]["close"] = 100.5
            self.assertEqual(lab.squeeze_dir(33, 6), "BUY")
            rows[30]["close"] = 99.5
            self.assertEqual(lab.squeeze_dir(33, 6), "SELL")
            rows[30]["close"] = 100.0
            self.assertIsNone(lab.squeeze_dir(33, 6))   # unresolved
        finally:
            lab.M15, lab.IDX = saved[0], saved[1]
            nl.M15, nl.IDX = saved[2], saved[3]
            pl.LEVELS = lab.build_levels(lab.M15)


class TestShippedCachedLedger(unittest.TestCase):
    def test_b71_contract_on_every_arm_row(self):
        res = _load(LEDGER)
        self.assertEqual(res["_time_stop_bars"], 144)   # 36h / M15 spacing
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
        self.assertEqual(_load(LEDGER)["_honesty_complaints"], [])

    def test_control_reproduces_round4_cached_number(self):
        # pdh_break wide on the cached set was round 4's ladder +0.627R n=54.
        c = _load(LEDGER)["pdh_w10_control"]["ladder"]
        self.assertEqual(c["trades"], 54)
        self.assertAlmostEqual(c["exp_R"], 0.627, places=3)

    def test_gate_is_neither_noop_nor_degenerate(self):
        p = _load(LEDGER)["_probe"]["k6"]
        self.assertGreater(p["pdh_signals"], 50)
        self.assertGreater(p["squeeze_resolved"], 15)
        self.assertLess(p["gate_share"], 0.8)      # actually filters
        self.assertGreater(p["agree"], 5)          # not the same arm twice
        self.assertGreater(p["disagree"], 5)

    def test_cached_gate_lowered_its_control(self):
        # The round's headline cached finding: unlike round 7's dayext gate,
        # the squeeze gate REDUCED per-trade R (0.627 -> 0.406/0.364) at
        # n=21/26 — recorded so the fresh comparison is honest about sign.
        res = _load(LEDGER)
        ctrl = res["pdh_w10_control"]["ladder_ts"]["exp_R"]
        self.assertLess(res["pdh_squeeze_agree_k6"]["ladder_ts"]["exp_R"], ctrl)
        self.assertLess(res["pdh_squeeze_agree_k8"]["ladder_ts"]["exp_R"], ctrl)


class TestShippedConfirmLedger(unittest.TestCase):
    """The fresh-set confirm settles the round's merit bar; pin its numbers
    so nobody quotes the fresh 0.603 without the cached 0.406 next to it."""

    def test_confirm_ledger_is_honest_and_complete(self):
        c = _load(CONFIRM)
        self.assertEqual(c["_honesty_complaints"], [])
        self.assertEqual(c["_time_stop_bars"], 144)
        for arm in ("CURRENT_FUNNEL", "pdh_w10_control",
                    "pdh_squeeze_agree_k6", "lane_funnel_then_pdh",
                    "lane_funnel_then_gated"):
            self.assertIn("ladder_ts", c[arm], arm)

    def test_gated_arm_loses_the_cached_bar_so_replacement_is_dead(self):
        # Merit bar needs BOTH sets: cached 0.406 vs funnel 0.854 already
        # rejects it regardless of the fresh number (0.603 > 0.590, n=40).
        cached = _load(LEDGER)
        self.assertLess(cached["pdh_squeeze_agree_k6"]["ladder_ts"]["exp_R"],
                        0.854)

    def test_fresh_gate_is_flat_not_lifted(self):
        c = _load(CONFIRM)
        ctrl = c["pdh_w10_control"]["ladder_ts"]
        gated = c["pdh_squeeze_agree_k6"]["ladder_ts"]
        # fresh: gate neither helps nor hurts materially (0.609 -> 0.603) —
        # the cached regression was small-sample noise, and the arm still
        # loses the funnel on cached. |delta| < 0.10R pins "flat".
        self.assertGreater(gated["trades"], 30)
        self.assertLess(abs(gated["exp_R"] - ctrl["exp_R"]), 0.10)

    def test_lane_comparison_gated_vs_ungated_same_bars(self):
        c = _load(CONFIRM)
        funnel = c["CURRENT_FUNNEL"]["ladder_ts"]
        raw = c["lane_funnel_then_pdh"]["ladder_ts"]
        gated = c["lane_funnel_then_gated"]["ladder_ts"]
        # Ungated pdh lane: adds volume and tot_R but doubles DD and dilutes
        # exp_R (round 4's shape, reproduced on this fetch).
        self.assertGreater(raw["trades"], funnel["trades"])
        self.assertGreater(raw["net_R"], funnel["net_R"])
        self.assertLess(raw["exp_R"], funnel["exp_R"])
        self.assertLess(raw["maxDD_R"], funnel["maxDD_R"])
        # Gated lane: buys the DD back (better than funnel's own) but adds
        # essentially ZERO total R — the gate removes the damage AND the
        # value. This is b70's decision data, same bars, same harness.
        self.assertLess(abs(gated["net_R"] - funnel["net_R"]),
                        abs(raw["net_R"] - funnel["net_R"]))
        self.assertGreater(gated["maxDD_R"], funnel["maxDD_R"])

    def test_stretch_probe_shows_gated_entries_more_stretched(self):
        # Mechanism: a squeeze that already resolved consumed part of the
        # move, so the gated day-break confirms further from the level.
        s = _load(CONFIRM)["_stretch_probe"]
        self.assertGreater(s["gated_k6"]["mean_stretch_atr"],
                           s["control"]["mean_stretch_atr"])
        self.assertGreater(s["gated_k6"]["n"], 20)


class TestRebind(unittest.TestCase):
    def test_rebind_points_all_modules_and_rebuilds_levels(self):
        saved = (lab.M15, lab.IDX, pl.M15, pl.LEVELS, nl.M15)
        saved_idx = (pl.IDX, nl.IDX)
        try:
            rows = [{"time": 1784109600 + 900 * i, "open": 1, "high": 2,
                     "low": 0.5, "close": 1.5} for i in range(10)]
            lab.rebind(rows)
            self.assertIs(lab.M15, rows)
            self.assertIs(pl.M15, rows)
            self.assertIs(nl.M15, rows)
            self.assertEqual(lab.IDX[rows[3]["time"]], 3)
            self.assertIs(pl.IDX, lab.IDX)
            self.assertIs(nl.IDX, lab.IDX)
            # 10 bars can never fill a >=40-bar trading day -> LEVELS rebuilt
            # empty (proving the rebuild ran on the NEW rows, not cached).
            self.assertEqual(pl.LEVELS, {})
        finally:
            lab.M15, lab.IDX = saved[0], saved[1]
            pl.M15, pl.LEVELS = saved[2], saved[3]
            nl.M15 = saved[4]
            pl.IDX = saved_idx[0]
            nl.IDX = saved_idx[1]
            lab.rebind(saved[0])   # canonical restore: IDX + LEVELS together


if __name__ == "__main__":
    unittest.main()
