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
    def test_B_vs_C_cliff_is_empty_gate_C_is_pruned_out(self):
        # b233b: THE structural finding of this round is gone. The rebuilt
        # map has book_C at zero trades on every leg — the RR 2.0 floor is
        # strict enough that no grade-C signal reaches the ladder at all.
        # So B_vs_C holds on 0-of-4 and every margin is None. The old pin
        # (4-of-4 holding, margins [0.272, 0.321, 0.275, 0.175]) described a
        # cliff that the current gate cannot see. The honest pin: the cliff
        # is not merely weaker, it is EMPTY, and the comparison must not be
        # faked by substituting 0.0 for None.
        self.assertEqual(self.v["B_vs_C"]["windows_holding"], 0)
        self.assertEqual(self.v["B_vs_C"]["of"], 4)
        self.assertFalse(self.v["B_vs_C"]["replicated_all_windows"])
        for m in self.v["B_vs_C"]["chronological_margins"]:
            self.assertIsNone(m,
                              "a B_minus_C margin exists where book_C has no "
                              "trades — a None was coerced to 0.0 somewhere")

    def test_B_minus_C_margins_are_unpriced_not_faked(self):
        # b233b: the pinned series [0.272, 0.321, 0.275, 0.175] is historical.
        # On the rebuilt map every entry is None because book_C is empty
        # (zero trades on all four legs). If these become numbers again,
        # the RR floor loosened and this pin must be re-read before either
        # the old cliff claim or this one is trusted.
        self.assertEqual(self.v["B_vs_C"]["chronological_margins"],
                         [None, None, None, None])

    # ---- 3. the same gate loses on total R: both axes must be quoted ----
    def test_ungated_earns_nothing_more_gate_C_is_pruned_out(self):
        # b233b: the "gate C loses on total R" axis is empty too. The RR 2.0
        # floor removes every grade-C signal, so loosening the gate has
        # nothing to add: 0-of-4 windows show ungated earning more, and both
        # the R-per-extra-trade and the DD delta are None or flat 0.0.
        # The old pin (4-of-4, every d_net > 0, marginal R in (0, 0.5))
        # described a trade-off that cannot exist when book_C is empty.
        g = self.v["live_gate_C_total_R"]
        self.assertEqual(g["windows_where_ungated_earns_more_net_R"], 0)
        for d_net in g["chronological_loosen_d_net_R"]:
            self.assertIn(d_net, (None, 0.0),
                          "a loosen-d_net appeared where no grade-C trades "
                          "exist — the empty book was given a fake margin")
        for marg in g["chronological_marginal_R_per_extra_trade"]:
            self.assertIsNone(marg,
                              "marginal R per extra trade computed on an "
                              "empty grade-C population")

    def test_gate_C_dissociation_is_moot_both_axes_empty(self):
        # b233b: the dissociation itself is gone. The old pin had both axes
        # at 4-of-4 (selection says keep the gate, volume says the dropped
        # trades were not garbage). On the rebuilt map both axes read 0-of-4
        # because book_C has zero trades on every leg — the RR 2.0 floor
        # prunes every grade-C signal before the ladder sees it. Pin both
        # axes reading 0 so the dissociation is recorded as MOOT, not as
        # silently supporting the gate either way.
        self.assertEqual(self.v["live_gate_C_out"]["windows_where_C_loses"], 0)
        self.assertEqual(
            self.v["live_gate_C_total_R"]
                 ["windows_where_ungated_earns_more_net_R"], 0)

    # ---- 4. the A/B flip is a direction property, not a rung property ----
    def test_A_vs_B_does_not_replicate(self):
        # b233b: windows_holding fell 3 -> 1 and the flip MOVED. W4 is empty
        # now (no M5 source), so the pinned "W4 is the losing window" cell
        # is unpriced. The losing window is W2 (margin -1.272) and W1 holds
        # at +0.25 — the flip survived the map change but sits in different
        # windows. The structural claim "A vs B breaks somewhere" still
        # holds; the cell that holds it moved.
        self.assertFalse(self.v["A_vs_B"]["replicated_all_windows"])
        self.assertEqual(self.v["A_vs_B"]["windows_holding"], 1)
        losing = [p for p in self.v["A_vs_B"]["per_window"]
                  if p["margin_exp_R"] is not None and not p["holds"]]
        self.assertEqual(len(losing), 1,
                         "expected exactly one priced non-holding A-vs-B cell")
        self.assertEqual(losing[0]["window"], "W2")
        self.assertLess(losing[0]["margin_exp_R"], 0.0)

    def test_W1_sell_book_is_the_A_flips_weak_side(self):
        # b233b: the flip MOVED from W4 to W1. W4 has no M5 source, so the
        # pinned "A-SELL on W4 is the weak book" cell is unpriced. On the
        # rebuilt map the A-vs-B flip lives in W1: A-SELL (0.219) still beats
        # B-SELL (-0.032), so the normal ordering holds on the newest window
        # and the flip's weak side is W2 (A-sell -1.006 vs B-sell +1.536).
        # The structural claim — the flip is a direction property, not a
        # rung property — survives, but in different windows.
        sbs = self.v["grade_by_side"]
        self.assertGreater(sbs["A"]["W1"]["buy"], sbs["B"]["W1"]["buy"])
        self.assertGreater(sbs["A"]["W1"]["sell"], sbs["B"]["W1"]["sell"])
        # the W2 sell cell is where the ordering inverts
        self.assertLess(sbs["A"]["W2"]["sell"], sbs["B"]["W2"]["sell"])
        # W3/W4 are unpriced — the side split must not fake numbers there
        for w in ("W3", "W4"):
            for side in ("buy", "sell"):
                self.assertIsNone(sbs["A"][w][side],
                                  f"A {w}/{side} is priced where the window "
                                  "has no M5 source — re-read this pin")

    def test_B_over_C_cliff_is_empty_and_A_vs_B_breaks_on_a_priced_cell(self):
        """b233b: the round's structural finding is gone. B beats C on NO
        window (book_C is empty — the RR 2.0 floor prunes every grade-C
        signal), while A vs B still breaks on one priced cell (W2 sell).
        So neither the old cliff at B nor the old W4 sell cell exists.
        'promote A over B' is still not supported by the side-split, but
        for a different reason: the comparison that would support it sits
        on one priced window. A future proposal must cite a ledger where
        these cells changed, not a feeling."""
        sbs = self.v["grade_by_side"]
        ab_broken = [(w, side) for w in WINDOWS for side in ("buy", "sell")
                     if sbs["A"][w][side] is not None
                     and sbs["B"][w][side] is not None
                     and sbs["A"][w][side] < sbs["B"][w][side]]
        self.assertGreater(len(ab_broken), 0,
                           "A vs B no longer breaks on any PRICED cell — "
                           "re-read this pin before quoting the flip")
        # C has no priced side anywhere: the cliff is empty, not merely weak
        bc_priced = [(w, side) for w in WINDOWS for side in ("buy", "sell")
                     if sbs["B"][w][side] is not None
                     and sbs["C"][w][side] is not None]
        self.assertEqual(bc_priced, [],
                         "a priced B-vs-C side cell exists — book_C came back "
                         "and the old cliff pins may need re-reading")

    # ---- tightening B to A: pays on 3-of-4, loses on the oldest draw ----
    def test_tighten_B_to_A_not_universal(self):
        # b233b: the "tighten B to A" trade-off shrank from 3 paying windows
        # giving up -261.7R to 1 paying window giving up +3.8R (i.e. it now
        # PAYS on W1 only and the net R given up is positive, not negative).
        # W3/W4 are unpriced and W2 has 2 trades, so the -261.7R figure was
        # carried by the inflated engine and the windows the floor removed.
        # The claim "not universal" survives — 1-of-4 paying is still not
        # universal — but the magnitude is completely different.
        t = self.v["tighten_B_to_A"]
        self.assertEqual(t["windows_paying"], 1)
        self.assertEqual(t["of"], 4)
        self.assertFalse(t["replicated_all_windows"])
        # positive means loosening (keeping B) would have paid, i.e. tightening
        # to A gives R up — the sign flipped from the old -261.7R pin
        self.assertGreater(t["total_net_R_given_up"], 0)

    # ---- 5. shipped cells ----
    def test_book_cells_pinned(self):
        # b233b: every cached/W4 cell here changed. The inflated pins were
        # book_A 51 trades / book_B 0.845R / book_C 0.470R and W4 0.588R /
        # 0.754R. On the rebuilt map book_C is empty (0 trades, no exp_R)
        # and W4's book_A/book_B are both unpriced — W4 has no M5 source.
        # The honest pins are the two surviving priced cached cells.
        cached = self.d["cached"]
        self.assertEqual(cached["book_A"]["ladder_ts"]["trades"], 34)
        self.assertAlmostEqual(cached["book_B"]["ladder_ts"]["exp_R"], 0.147)
        self.assertIsNone(cached["book_C"]["ladder_ts"]["exp_R"],
                          "book_C has an exp_R — the RR floor loosened and "
                          "the B-vs-C cliff may have returned; re-read this "
                          "pin and the B_vs_C pins")
        w4 = self.d["W4"]
        self.assertIsNone(w4["book_A"]["ladder_ts"]["exp_R"],
                          "W4 book_A is priced where no M5 source exists")
        self.assertIsNone(w4["book_B"]["ladder_ts"]["exp_R"],
                          "W4 book_B is priced where no M5 source exists")

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
