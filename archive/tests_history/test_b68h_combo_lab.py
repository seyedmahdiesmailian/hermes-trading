"""b68 round 7 (NR7 x day-extension combination lab) — integrity pins.

This is the FIRST round built entirely on the b71 harness (engines.lab_harness),
so the pins cover both the round's own logic and the harness contract as
actually consumed by a lab script:

1. combo() is a PURE INTERSECTION: geometry comes from nr7_break unchanged;
   the dayext arm is only a direction oracle. A disagreement or a silent gate
   must return None, and an agreement must return the nr7 dict byte-identical
   (no new stop geometry can sneak in — the b69/round-6 trap class).
2. Anti-vacuity from the SHIPPED JSON (data/backtest/b68h_combo_lab.json):
   the gate must actually filter (gate_share well under 1) and must NOT be
   degenerate (agree and disagree both > 0 — a 100%/0% split would mean the
   two arms are the same arm, which would make the "combination" fake).
3. The b71 contract on the shipped ledger: every arm row carries ladder_ts
   and the hold columns, and the honesty summary is empty (the round passed
   its own gate).
4. rebind() repoints ALL THREE module-level datasets (lab + both ingredient
   modules) — the confirm's fresh-fetch pattern silently measuring a mix of
   cached and fresh bars would be the worst possible lab bug.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68h_combo_lab as lab  # noqa: E402

LEDGER = os.path.join(ROOT, "data", "backtest", "b68h_combo_lab.json")
ARMS = ("nr7_w10_control", "nr7_dayext_agree", "nr7_dayext_agree_e25")


def _load():
    with open(LEDGER) as f:
        return json.load(f)


class TestComboIsPureIntersection(unittest.TestCase):
    def setUp(self):
        self.saved = (lab.nl.nr7_break, lab.dl.dayext)

    def tearDown(self):
        lab.nl.nr7_break, lab.dl.dayext = self.saved

    def test_agreement_returns_the_nr7_dict_unchanged(self):
        sig7 = {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 102.0,
                "style": "nr7_break", "grade": "B"}
        lab.nl.nr7_break = lambda i, wide=True: sig7
        lab.dl.dayext = lambda i, m="cont", s="atr", ext=1.5: {"side": "BUY"}
        self.assertIs(lab.combo(50), sig7)   # same object — zero mutation

    def test_disagreement_is_dropped(self):
        sig7 = {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 102.0}
        lab.nl.nr7_break = lambda i, wide=True: sig7
        lab.dl.dayext = lambda i, m="cont", s="atr", ext=1.5: {"side": "SELL"}
        self.assertIsNone(lab.combo(50))

    def test_silent_gate_is_dropped(self):
        sig7 = {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 102.0}
        lab.nl.nr7_break = lambda i, wide=True: sig7
        lab.dl.dayext = lambda i, m="cont", s="atr", ext=1.5: None
        self.assertIsNone(lab.combo(50))

    def test_no_nr7_signal_short_circuits_the_gate(self):
        called = []
        lab.nl.nr7_break = lambda i, wide=True: None
        lab.dl.dayext = lambda i, m="cont", s="atr", ext=1.5: (
            called.append(i) or {"side": "BUY"})
        self.assertIsNone(lab.combo(50))
        self.assertEqual(called, [])   # gate never consulted — pure AND


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

    def test_control_reproduces_round5_cached_number(self):
        # nr7_break wide on the cached set was round 5's ladder +0.598R n=218.
        # The control arm here is the SAME signal through the SAME engine; if
        # the harness or the rebind changed the measurement, this breaks.
        c = _load()["nr7_w10_control"]["ladder"]
        self.assertEqual(c["trades"], 218)
        self.assertAlmostEqual(c["exp_R"], 0.598, places=3)

    def test_gate_is_neither_noop_nor_degenerate(self):
        p = _load()["_probe"]["e15"]
        self.assertGreater(p["nr7_signals"], 100)
        self.assertGreater(p["dayext_gate_fires"], 50)
        # filters hard (a no-op gate would read gate_share ~ 1)
        self.assertLess(p["gate_share"], 0.8)
        # ...but is NOT the same arm twice (a fake combination would show a
        # 0% or 100% agree split)
        self.assertGreater(p["agree"], 20)
        self.assertGreater(p["disagree"], 20)


class TestShippedConfirmLedger(unittest.TestCase):
    """The fresh-set confirm (scripts/b68h_confirm_combo.py) is what settles
    the round's merit bar; pin its numbers so nobody re-quotes the cached
    +0.622 as a candidate without the fresh +0.587 next to it."""

    P = os.path.join(ROOT, "data", "backtest", "b68h_combo_confirm.json")

    def test_confirm_ledger_is_honest_and_complete(self):
        with open(self.P) as f:
            c = json.load(f)
        self.assertEqual(c["_honesty_complaints"], [])
        self.assertEqual(c["_time_stop_bars"], 144)
        for arm in ("CURRENT_FUNNEL", "nr7_w10_control", "nr7_dayext_agree",
                    "lane_funnel_then_combo"):
            self.assertIn("ladder_ts", c[arm], arm)

    def test_combo_loses_the_fresh_bar_and_the_lane_adds_no_edge(self):
        with open(self.P) as f:
            c = json.load(f)
        funnel = c["CURRENT_FUNNEL"]["ladder_ts"]
        combo = c["nr7_dayext_agree"]["ladder_ts"]
        lane = c["lane_funnel_then_combo"]["ladder_ts"]
        # merit bar: the gate lifts the control (0.519 -> 0.587 fresh) but
        # still loses the funnel on fresh (0.587 < 0.590) and on cached
        # (0.622 < 0.854) -> REJECTED as replacement.
        self.assertLess(combo["exp_R"], funnel["exp_R"])
        self.assertGreater(combo["trades"], 100)   # a real sample, not n=4
        # the lane trades MORE than the funnel alone but at LOWER per-trade R
        # and worse DD -> the gated nr7 does NOT earn a slot either (b70).
        self.assertGreater(lane["trades"], funnel["trades"])
        self.assertLess(lane["exp_R"], funnel["exp_R"])
        self.assertLess(lane["maxDD_R"], funnel["maxDD_R"])


class TestRebind(unittest.TestCase):
    def test_rebind_points_all_three_modules_at_the_new_rows(self):
        saved = lab.M15, lab.IDX, lab.nl.M15, lab.dl.M15
        try:
            rows = [{"time": 1784109600 + 900 * i, "open": 1, "high": 2,
                     "low": 0.5, "close": 1.5} for i in range(10)]
            lab.rebind(rows)
            self.assertIs(lab.M15, rows)
            self.assertIs(lab.nl.M15, rows)
            self.assertIs(lab.dl.M15, rows)
            self.assertEqual(lab.IDX[rows[3]["time"]], 3)
            self.assertIs(lab.nl.IDX, lab.IDX)
            self.assertIs(lab.dl.IDX, lab.IDX)
        finally:
            lab.M15, lab.IDX = saved[0], saved[1]
            lab.nl.M15, lab.dl.M15 = saved[2], saved[3]
            lab.nl.IDX = {r["time"]: n for n, r in enumerate(lab.nl.M15)}
            lab.dl.IDX = lab.nl.IDX


if __name__ == "__main__":
    unittest.main()
