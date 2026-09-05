"""b68 round 18 (b68r) — the grade ladder itself measured as books.

Why this exists: b80 fixed the funnel baseline to carry the live grade gate
(min_grade=B), but the LADDER (A>B>C) had never been measured as a first-class
object on the corrected bar. Every round since b80 quotes funnel 0.68R — the
number that IS the gate's output — yet nobody had asked: does the rung ordering
replicate across independent windows, does the live B-over-C gate earn its keep
on BOTH R axes, and is the A/B flip a rung property or a direction property
(b78's mix question taken to its end)?

Pins, in order of what would rot first:

1. REPRODUCTION (integrity): the funnel book (gate B) reproduces b80's shipped
   gradeB funnel column on every leg. If this fails, this lab's signal capture
   drifted from b80's and every verdict below is meaningless.
2. THE LIVE GATE EARNS ITS KEEP ON SELECTION: B beats C on exp_R in ALL FOUR
   independent windows (chronological margins pinned), so min_grade=B stays.
3. THE SAME GATE LOSES ON TOTAL R: the ungated book earns MORE net_R on all
   four windows (+29..+57R) because its marginal trade is still +0.21..+0.37R.
   The gate is a quality-per-trade filter that pays volume — quoting either
   axis alone lies (b81's rule).
4. THE A/B FLIP IS NOT A RUNG PROPERTY: A beats B on 3-of-4 windows, and the
   broken cells (W4 sell 0.085 vs 0.734, W2 buy 0.677 vs 0.711) are SIDE
   cells, not the rung — while B > C holds on ALL EIGHT window/side cells.
   A future "promote A over B" proposal must die here.
5. THE SHIPPED NUMBERS: verdict cells pinned to the JSON so a re-run that
   changes data is a deliberate re-measurement, not silent drift.
6. READ-ONLY ISOLATION: no live-path module imports the lab script.
"""
import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest", "b68r_grade_ladder.json")
PARITY = os.path.join(ROOT, "data", "backtest", "b80_gate_parity.json")
WINDOWS = ("W1", "W2", "W3", "W4")
CHRONO = ("W4", "W3", "W2", "W1")
BOOKS = ("A", "B", "C")


def _load(path):
    with open(path) as f:
        return json.load(f)


@unittest.skipUnless(os.path.exists(LEDGER) and os.path.exists(PARITY),
                     "b68r/b80 ledgers not shipped yet")
class TestB68rGradeLadder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = _load(LEDGER)
        cls.p = _load(PARITY)
        cls.v = cls.d["_verdict"]

    # ---- 1. reproduction: funnel book == b80's gradeB funnel column ----
    def test_funnel_book_reproduces_b80_gradeB(self):
        for leg in ("cached",) + WINDOWS:
            mine = self.d[leg]["gateB"]["ladder_ts"]
            theirs = self.p["legs"][leg]["gradeB"]
            self.assertEqual(mine["trades"], theirs["trades"],
                             f"{leg}: trade count drifted from b80")
            self.assertAlmostEqual(mine["exp_R"], theirs["exp_R"], places=3,
                                   msg=f"{leg}: exp_R drifted from b80")

    # ---- 2. the live gate earns its keep on selection, all four windows ----
    def test_B_beats_C_all_windows(self):
        self.assertEqual(self.v["B_vs_C"]["windows_holding"], 4)
        self.assertEqual(self.v["B_vs_C"]["of"], 4)
        self.assertTrue(self.v["B_vs_C"]["replicated_all_windows"])
        for m in self.v["B_vs_C"]["chronological_margins"]:
            self.assertGreater(m, 0.0)

    def test_B_minus_C_margins_pinned(self):
        self.assertEqual(self.v["B_vs_C"]["chronological_margins"],
                         [0.272, 0.321, 0.275, 0.175])

    # ---- 3. the same gate loses on total R: both axes must be quoted ----
    def test_ungated_earns_more_total_R_everywhere(self):
        g = self.v["live_gate_C_total_R"]
        self.assertEqual(g["windows_where_ungated_earns_more_net_R"], 4)
        for d_net in g["chronological_loosen_d_net_R"]:
            self.assertGreater(d_net, 0.0)
        # and the marginal trade is positive everywhere — that is WHY:
        for marg in g["chronological_marginal_R_per_extra_trade"]:
            self.assertGreater(marg, 0.0)
            self.assertLess(marg, 0.5)   # ...but below the kept book's bar

    def test_gate_C_out_and_gate_C_total_R_disagree(self):
        """The dissociation itself: selection says keep the gate, volume says
        the dropped trades were not garbage. Pin both verdicts so neither can
        be quietly dropped from a future summary."""
        self.assertEqual(self.v["live_gate_C_out"]["windows_where_C_loses"], 4)
        self.assertEqual(
            self.v["live_gate_C_total_R"]
                 ["windows_where_ungated_earns_more_net_R"], 4)

    # ---- 4. the A/B flip is a direction property, not a rung property ----
    def test_A_vs_B_does_not_replicate(self):
        self.assertFalse(self.v["A_vs_B"]["replicated_all_windows"])
        self.assertEqual(self.v["A_vs_B"]["windows_holding"], 3)
        # the losing window is W4 (oldest draw), margin negative there
        w4 = [p for p in self.v["A_vs_B"]["per_window"] if p["window"] == "W4"]
        self.assertEqual(len(w4), 1)
        self.assertFalse(w4[0]["holds"])
        self.assertLess(w4[0]["margin_exp_R"], 0.0)

    def test_W4_flip_is_the_A_sell_book(self):
        sbs = self.v["grade_by_side"]
        # A-buy on W4 is fine (near the B-buy cell); A-SELL is the weak book.
        self.assertGreater(sbs["A"]["W4"]["buy"], 0.5)
        self.assertLess(sbs["A"]["W4"]["sell"], 0.25)
        self.assertGreater(sbs["B"]["W4"]["sell"], sbs["A"]["W4"]["sell"])
        # and on the NEWEST window the ordering is normal on both sides —
        # the flip is not a property of the rung.
        self.assertGreater(sbs["A"]["W1"]["buy"], sbs["B"]["W1"]["buy"])
        self.assertGreater(sbs["A"]["W1"]["sell"], sbs["B"]["W1"]["sell"])

    def test_B_over_C_is_the_real_cliff_A_over_B_is_noise(self):
        """The round's structural finding, pinned per-cell: B beats C on EVERY
        window/side cell (the cliff is at B), while A vs B breaks on at least
        one cell (W4 sell) — so 'promote A over B' is NOT supported by the
        side-split either. A future tightening proposal must cite a ledger
        where these cells changed, not a feeling."""
        sbs = self.v["grade_by_side"]
        ab_broken = [w for w in WINDOWS for side in ("buy", "sell")
                     if sbs["A"][w][side] < sbs["B"][w][side]]
        bc_broken = [w for w in WINDOWS for side in ("buy", "sell")
                     if sbs["B"][w][side] < sbs["C"][w][side]]
        self.assertGreater(len(ab_broken), 0)
        self.assertEqual(bc_broken, [])

    # ---- tightening B to A: pays on 3-of-4, loses on the oldest draw ----
    def test_tighten_B_to_A_not_universal(self):
        t = self.v["tighten_B_to_A"]
        self.assertEqual(t["windows_paying"], 3)
        self.assertFalse(t["replicated_all_windows"])
        self.assertLess(t["total_net_R_given_up"], -200.0)

    # ---- 5. shipped cells ----
    def test_book_cells_pinned(self):
        cached = self.d["cached"]
        self.assertEqual(cached["book_A"]["ladder_ts"]["trades"], 51)
        self.assertAlmostEqual(cached["book_B"]["ladder_ts"]["exp_R"], 0.845)
        self.assertAlmostEqual(cached["book_C"]["ladder_ts"]["exp_R"], 0.470)
        w4 = self.d["W4"]
        self.assertAlmostEqual(w4["book_A"]["ladder_ts"]["exp_R"], 0.588)
        self.assertAlmostEqual(w4["book_B"]["ladder_ts"]["exp_R"], 0.754)

    def test_regime_drift_fact_shipped(self):
        """The legs span a 4x ATR regime swing (W4 4.3 -> W2 16.3): any claim
        that a rung 'always' ranks better must survive that, and it doesn't."""
        atrs = [self.d[w]["_atr_mean"] for w in WINDOWS]
        self.assertGreater(max(atrs) / min(atrs), 3.0)

    def test_mix_shipped_per_book_per_leg(self):
        for leg in ("cached",) + WINDOWS:
            for g in BOOKS:
                mix = self.d[leg]["book_" + g]["_mix"]
                self.assertIn("buy", mix)
                self.assertIn("sell", mix)
                self.assertEqual(mix["buy"] + mix["sell"], mix["trades"])

    # ---- 6. read-only isolation ----
    def test_no_live_module_imports_the_lab(self):
        live = [f for f in os.listdir(ROOT)
                if f.startswith("hermes_") and f.endswith(".py")]
        for fname in live:
            with open(os.path.join(ROOT, fname)) as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                for m in mods:
                    self.assertNotIn("b68r_grade_ladder", m,
                                     f"{fname} imports the lab")


if __name__ == "__main__":
    unittest.main()
