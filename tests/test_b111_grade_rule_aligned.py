"""b111 — THE WATCHDOG'S GRADE RULE IS NOW THE CANONICAL ONE, AND THE
DIVERGENCE IT REMOVED WAS MEASURED INERT BEFORE IT WAS TOUCHED.

b109 filed b111 as a HUMAN-GATE decision: "aligning the watchdog onto
_infer_setup_grade would change the live breakeven lock, so it needs its own
measured round". This round took the measurement first, and the premise did
not survive it.

THE MEASUREMENT (scripts/b111_blast_radius_probe.py, ledger
data/backtest/b111_blast_radius.json):

  * 44 cells of the (alignment, trend, regime) space differ on GRADE between
    the canonical rule and the watchdog's inline pre-b45 copy.
  * Only 9 of those 44 differ on a BROKER-VISIBLE action, and all 9 are one
    family: aligned + trend>=3.0 + a NON-continuation regime (canonical -> B
    -> close 100% at TP1; watchdog -> A -> keep a 0.3 runner -> the +0.15R
    breakeven lock fires). The other 35 differ only in the reason LABEL
    ('weak_full_exit_at_tp1' vs 'balanced_full_exit_at_tp1'), and post-b55
    both carry close_fraction 1.0, which auto_executor routes to
    bridge.close_position. A label is not an outcome.
  * That one differing family is UNREACHABLE: engines.context._detect_regime
    returns a continuation regime for EVERY aligned + strong-trend geometry
    (0 of 320 swept vote x trend x price-geometry cells produce a
    non-continuation regime), and 0 of the 65 real plans with
    aligned & trend>=3.0 had one. The producer cannot emit the input the
    divergence needs.
  * Replaying the 17 executed trades whose plan snapshot survives: 0 action
    differences. In the frame the watchdog actually runs in (the 65 plan
    snapshots taken while a position was open): 0 differences.
  * The canonical rule is never LOOSER than the removed one (0 cells where
    its grade is higher), so aligning cannot widen a risk gate.

WHY THIS IS NOT A NO-OP: the two rules DID differ on 18.8% of all plans in the
weak-vs-balanced label, and the watchdog's looser A was one threshold away from
a real behaviour change. The fix removes a latent divergence and the three-
lookalikes structure that produced it (the b109 lesson), not a live number.

The pins below certify: the shared definition exists and is the only one, the
watchdog uses it, the measurement artifact reproduces, and the inertness claims
are arithmetic facts about the code rather than prose in a backlog.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines.plan import setup_grade  # noqa: E402
from engines.trade_management import (  # noqa: E402
    _partial_close_fraction, ladder_fields)

LEDGER = os.path.join(ROOT, "data", "backtest", "b111_blast_radius.json")

CONT = {"breakout_continuation", "pullback_continuation"}


def pre_b45_watchdog_grade(alignment: str, trend: float, regime: str) -> str:
    """The rule b111 REMOVED from position_daemon.build_trade, restated here
    as the historical control so the inertness claim stays checkable."""
    if alignment == "aligned" and trend >= 3.0:
        return "A"
    if alignment in ("aligned", "mixed") and trend >= 1.2:
        return "B"
    return "C"


def canonical_grade(alignment: str, trend: float, regime: str) -> str:
    return setup_grade({"quality": {"alignment": alignment,
                                    "trend_strength": trend,
                                    "regime": regime}})


def broker_visible(quality: dict, grade: str) -> list:
    """The action+payload sequence the live callers would issue, with the
    reason label stripped — the same projection the probe uses."""
    from datetime import datetime, timedelta, timezone
    from engines.trade_management import evaluate_trade_management
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    entry, sl, tp = 4300.0, 4320.0, 4260.0
    t = {"symbol": "XAUUSD", "side": "SELL", "entry_price": entry, "sl": sl,
         "tp_levels": [entry + (tp - entry) * 0.5, tp],
         "tp_shares": [0.5, 0.3, 0.2], "scale_in_levels": [],
         "filled_tp_levels": [], "breakeven_active": False,
         "runner_active": True, "scaled_in_levels": [], "volume": 0.10,
         "setup_grade": grade,
         **{k: v for k, v in ladder_fields(quality, grade).items()
            if k != "setup_grade"}}
    tp1 = entry + (tp - entry) * 0.5
    out = []
    a = evaluate_trade_management(t, tp1, now)
    out.append((a.get("action"), a.get("close_fraction")))
    if a.get("action") == "partial_take_profit":
        if float(a.get("close_fraction") or 0) >= 1.0:
            out.append(("TICKET_CLOSED_AT_TP1", None))
            return out
        t["filled_tp_levels"] = [a.get("target_hit")]
    b = evaluate_trade_management(t, tp1, now + timedelta(seconds=5))
    out.append((b.get("action"), b.get("new_sl")))
    return out


class TestB111OneDefinition(unittest.TestCase):
    """The structural half of the fix: the grade rule exists ONCE."""

    def _grade_rule_bodies(self, path, names):
        """Return {fn_name: body} for the named functions in a file."""
        with open(path) as fh:
            tree = ast.parse(fh.read(), filename=path)
        out = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in names:
                out[node.name] = [ast.dump(s) for s in node.body
                                  if not isinstance(s, ast.Expr)
                                  or not isinstance(s.value, ast.Constant)]
        return out

    def test_b111_the_grade_rule_is_defined_in_exactly_one_place(self):
        # b109's disease was three lookalike derivations that drifted. The
        # grade had the same shape: a copy in engines/auto_executor.py, a copy
        # in hermes_runtime.py, and a looser inline rule in position_daemon.py.
        # Now there is one definition and the others are aliases that CALL it.
        producers = {
            os.path.join(ROOT, "engines", "auto_executor.py"):
                "_infer_setup_grade",
            os.path.join(ROOT, "hermes_runtime.py"): "_infer_setup_grade",
        }
        for path, fn in producers.items():
            bodies = self._grade_rule_bodies(path, [fn])
            self.assertIn(fn, bodies, f"{fn} vanished from {path}")
            stmts = bodies[fn]
            self.assertEqual(len(stmts), 1,
                             f"{path}: {fn} has a {len(stmts)}-statement body "
                             "again — it must be a thin alias of "
                             "engines.plan.setup_grade (b111)")
            self.assertIn("setup_grade", "".join(stmts),
                          f"{path}: {fn} no longer delegates to the shared rule")
        # and the watchdog must not restate it either
        with open(os.path.join(ROOT, "position_daemon.py")) as fh:
            src = fh.read()
        self.assertIn("wd_grade = setup_grade(plan)", src,
                      "the watchdog no longer calls the shared grade rule")

    def test_b111_engines_plan_stays_a_leaf(self):
        # The shared definition is only safe if importing it cannot create a
        # cycle: engines/plan.py must import stdlib (and engines.plan-internal
        # names) and nothing from the trading modules that import IT.
        with open(os.path.join(ROOT, "engines", "plan.py")) as fh:
            tree = ast.parse(fh.read(), filename="plan.py")
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module)
        forbidden = {"auto_executor", "trade_management", "orchestrator",
                     "context", "risk", "defcon", "legacy_guards"}
        bad = {m for m in mods if m.split(".")[-1] in forbidden}
        self.assertEqual(bad, set(),
                         f"engines/plan.py now imports {bad} — the shared grade "
                         "rule would create an import cycle and the producers "
                         "would go back to copies")


class TestB111Inertness(unittest.TestCase):
    """The measurement half: the removed divergence changed no outcome."""

    def test_b111_the_only_differing_cell_family_is_the_unreachable_one(self):
        import itertools
        alignments = ["aligned", "mixed", "neutral", "counter"]
        trends = [0.0, 0.3, 0.5, 0.8, 1.19, 1.2, 1.3, 2.0, 2.9, 3.0, 4.0, 6.0]
        regimes = ["breakout_continuation", "pullback_continuation", "range",
                   "reversal", "none"]
        grade_diff = outcome_diff = 0
        families = set()
        for al, tr, rg in itertools.product(alignments, trends, regimes):
            g_new = canonical_grade(al, tr, rg)
            g_old = pre_b45_watchdog_grade(al, tr, rg)
            if g_new == g_old:
                continue
            grade_diff += 1
            q = {"alignment": al, "trend_strength": tr, "regime": rg}
            if broker_visible(q, g_new) != broker_visible(q, g_old):
                outcome_diff += 1
                families.add((al, g_new, g_old))
        self.assertEqual(grade_diff, 44,
                         f"the two rules now differ on {grade_diff} cells, not "
                         "the 44 b111 measured — re-read the probe")
        self.assertEqual(outcome_diff, 9,
                         f"{outcome_diff} cells differ at the broker, not the "
                         "9 b111 measured — the blast radius changed")
        self.assertEqual(families, {("aligned", "B", "A")},
                         f"outcome-differing families grew: {families}")

    def test_b111_the_producer_cannot_emit_the_differing_cell(self):
        # The 9 differing cells all need aligned + trend>=3.0 + a
        # NON-continuation regime. Feed the REAL producers every TF vote
        # combination and trend/price geometry: if a non-continuation regime
        # ever comes out, the removed watchdog A was reachable and this fix
        # was NOT inert — it needs its own measured round.
        import itertools
        from engines.context import _alignment_label, _detect_regime
        swept = reachable = 0
        for m5, h1, h4 in itertools.product(
                ["bullish", "bearish", "neutral"], repeat=3):
            al = _alignment_label(m5, h1, h4)
            if al != "aligned":
                continue
            bias = h4 if h4 != "neutral" else h1
            if bias == "neutral":
                bias = m5
            for tr in (3.0, 3.5, 6.0, 12.0):
                for dv in (-2.0, -0.3, 0.0, 0.3, 2.0):
                    for atr in (1.0, 5.0):
                        rg = _detect_regime(
                            bias=bias, alignment=al, trend_strength=tr,
                            last_price=110.0 + dv * atr, value_low=100.0,
                            value_high=110.0, atr=atr, m5_bias=m5,
                            h1_bias=h1, h4_bias=h4)
                        swept += 1
                        if rg not in CONT:
                            reachable += 1
        self.assertEqual(swept, 320, "the reachability sweep shrank")
        self.assertEqual(
            reachable, 0,
            f"engines.context produced {reachable}/320 aligned+strong-trend "
            "cells with a NON-continuation regime — the watchdog's looser A "
            "is reachable after all, so removing it was a live behaviour "
            "change and b111 must be re-measured, not re-pinned")

    def test_b111_the_canonical_rule_is_never_looser(self):
        # Hard-rule guard: this change must not widen a risk gate. Over the
        # whole swept space, the canonical grade must be <= the removed rule's.
        import itertools
        rank = {"A": 3, "B": 2, "C": 1}
        looser = []
        for al, tr, rg in itertools.product(
                ["aligned", "mixed", "neutral", "counter", ""],
                [0.0, 0.5, 1.19, 1.2, 2.0, 2.9, 3.0, 3.1, 6.0],
                ["breakout_continuation", "pullback_continuation", "range",
                 "trending", "reversal", "none", None]):
            if rank[canonical_grade(al, tr, str(rg))] > rank[
                    pre_b45_watchdog_grade(al, tr, str(rg))]:
                looser.append((al, tr, rg))
        self.assertEqual(looser, [],
                         f"the canonical grade is looser on {looser[:5]} — "
                         "aligning would have WIDENED the gate")

    def test_b111_the_reason_label_split_is_not_an_outcome(self):
        # The 35 label-only cells: both labels carry close_fraction 1.0, which
        # auto_executor routes to bridge.close_position. Pinning this keeps
        # nobody from "discovering" the weak/balanced split as a live risk.
        q = {"alignment": "mixed", "trend_strength": 2.0, "regime": "range"}
        g_new, g_old = canonical_grade("mixed", 2.0, "range"), \
            pre_b45_watchdog_grade("mixed", 2.0, "range")
        self.assertEqual((g_new, g_old), ("C", "B"))
        base = {"side": "SELL", "entry_price": 4300.0, "sl": 4320.0}
        s_new = _partial_close_fraction(
            {**base, **ladder_fields(q, g_new)})
        s_old = _partial_close_fraction(
            {**base, **ladder_fields(q, g_old)})
        self.assertEqual(s_new[0], s_old[0],
                         "the weak/balanced split now differs in SHARE — it is "
                         "no longer a label-only difference")
        self.assertEqual(s_new[1], "weak_full_exit_at_tp1")
        self.assertEqual(s_old[1], "balanced_full_exit_at_tp1")
        self.assertGreaterEqual(s_new[0], 1.0,
                                "a share <1.0 here means the ticket survives "
                                "TP1 and the breakeven lock becomes reachable")


class TestB111Ledger(unittest.TestCase):
    """The shipped probe's numbers, pinned from the artifact itself."""

    def _led(self):
        if not os.path.exists(LEDGER):
            self.skipTest("b111 ledger not present")
        with open(LEDGER) as fh:
            return json.load(fh)

    def test_b111_the_ledger_agrees_with_the_in_suite_recomputation(self):
        led = self._led()
        self.assertEqual(led["cells"]["cells_differing_in_grade"], 44)
        self.assertEqual(led["cells"]["cells_differing_in_outcome"], 9)
        self.assertEqual(led["cells"]["cells_differing_in_reason_label_only"], 35)
        self.assertEqual(
            led["reachability"]["producing_a_non_continuation_regime"], 0)
        self.assertEqual(led["live_replay"]["differing"], 0,
                         "the live replay found an action difference — b111 "
                         "was not inert, re-read it")

    def test_b111_the_watchdog_frame_census_found_no_differing_snapshot(self):
        # b113's rule applied to b111 itself: b109's 18.8% was a census over
        # ALL plan snapshots, but the watchdog only builds a trade dict while a
        # position is open. In THAT frame the drift is 10/65 snapshots by
        # label and 0/65 by outcome.
        led = self._led()
        wf = led["watchdog_frame"]
        self.assertGreater(wf["snapshots_while_position_open"], 0,
                           "no snapshots fall inside a position window — the "
                           "frame census is vacuous")
        self.assertEqual(wf["outcome_differing_in_frame"], 0)

    def test_b111_the_live_replay_covers_the_executed_book(self):
        led = self._led()
        lr = led["live_replay"]
        self.assertGreaterEqual(lr["replayed"], 15,
                                "the executed-trade join lost coverage — the "
                                "inertness claim is no longer measured on the "
                                "real book")
        self.assertEqual(lr["executed_trades"], lr["replayed"]
                         + lr["plan_snapshot_missing"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
