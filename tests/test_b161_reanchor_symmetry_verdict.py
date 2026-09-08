#!/usr/bin/env python3
"""b161 — the reanchor-symmetry question is CLOSED BY EVIDENCE; pin it shut.

b160 found that engines/plan._reanchor_blueprint picks the NEAREST target for
BUY and the FURTHEST for SELL while its docstring promised "furthest" for
both, and measured ONE leg (cached, delta 0.000R) — a direction report, not a
verdict (b129's floor). b161 ran the same two arms on W1..W4 and merged all
five legs (scripts/b161_merge_verdict.py ->
data/backtest/b161_reanchor_symmetry_verdict.json):

    cached 0.000 · W1 -0.006 · W2 0.000 · W3 0.000 · W4 0.000
    legs where the symmetric arm is BETTER: 0

Plus a binding census (scripts/b161_reanchor_binding_census.py): the pick
difference actually binds on 0.7-1.7% of BUY signals per leg, and a divergence
probe (scripts/b161_w1_divergence_probe.py) shows W1's -0.006R is a single
bound signal (index 2984, rr 1.55 -> 1.655) cascading through the
one-position-at-a-time slot book (2 incumbent trades swap for 3 symmetric
ones) — not a systematic cost.

VERDICT: retire the question. The asymmetry is inert on the current funnel;
the docstring now states the asymmetry as measured intent. What this file
pins:

 1. the shipped verdict ledger's exact five deltas + 0-better-legs call
    (and that the producer still re-merges to it — b127's rule, exercised);
 2. the binding census numbers per leg against the shipped ledger, including
    that every bound signal is BUY (SELL's max-pick is untouched by the arm);
 3. the incumbent asymmetry IN THE CODE (AST: BUY min, SELL max) so a
    cosmetic "symmetry fix" fails loudly without new evidence;
 4. ANTI-VACUITY: on a synthetic blueprint with two clearing candidates the
    two arms provably produce different targets (the pin in (3) is about real
    divergent behaviour, not a function that can never differ);
 5. the W1 divergence probe ledger agrees with the verdict's W1 row.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from engines import plan as plan_mod                      # noqa: E402


VERDICT_PATH = os.path.join(_ROOT, "data", "backtest",
                            "b161_reanchor_symmetry_verdict.json")
CENSUS_PATH = os.path.join(_ROOT, "data", "backtest",
                           "b161_reanchor_binding_census.json")
W1PROBE_PATH = os.path.join(_ROOT, "data", "backtest",
                            "b161_w1_divergence.json")


def _load(p):
    with open(p) as fh:
        return json.load(fh)


class TestB161VerdictLedger(unittest.TestCase):

    def test_b161_five_leg_deltas_are_as_shipped(self):
        led = _load(VERDICT_PATH)
        self.assertEqual(led["verdict"]["per_leg_delta_exp_R"],
                         {"cached": 0.0, "W1": -0.006, "W2": 0.0, "W3": 0.0,
                          "W4": 0.0})
        self.assertEqual(led["verdict"]["legs_symmetric_better"], 0,
                         "a leg where symmetric is BETTER means the retirement "
                         "was wrong — reopen b161, do not edit this test")
        self.assertEqual(sorted(led["legs"]),
                         ["W1", "W2", "W3", "W4", "cached"])
        self.assertFalse(led["verdict"]["b129_floor_met"],
                         "only one non-zero leg: below b129's 3-leg decision "
                         "floor, which is exactly why NOTHING ships")

    def test_b161_producer_still_remerges_the_ledger(self):
        from scripts import b161_merge_verdict as b161
        led = _load(VERDICT_PATH)
        got = b161.merge()
        self.assertEqual(got["legs"], led["legs"])
        self.assertEqual(got["verdict"], led["verdict"])

    def test_b161_identical_books_on_four_of_five_legs(self):
        led = _load(VERDICT_PATH)
        ident = [k for k, v in led["legs"].items() if v["identical_book"]]
        self.assertEqual(sorted(ident), ["W2", "W3", "W4", "cached"])
        # W1's whole delta is 1 extra trade and a swapped slot book
        w1 = led["legs"]["W1"]
        self.assertEqual(w1["incumbent"]["trades"], 181)
        self.assertEqual(w1["symmetric"]["trades"], 182)


class TestB161BindingCensus(unittest.TestCase):

    def test_b161_binding_is_rare_and_buy_only(self):
        led = _load(CENSUS_PATH)
        legs = led["legs"]
        self.assertEqual(sorted(legs), ["W1", "W2", "W3", "W4", "cached"])
        for leg, row in legs.items():
            self.assertEqual(list(row["by_side"]), ["BUY"],
                             f"{leg}: a SELL-bound pick means the arm touched "
                             "the untouched branch — the A/B is no longer pure")
            self.assertLessEqual(row["bound_share"], 0.02,
                                 f"{leg}: pick binds on >2% of signals — the "
                                 "'dormant' claim behind b161's retirement is "
                                 "no longer true on this leg")
            for rec in row["by_side"]["BUY"]:
                self.assertLessEqual(rec["rr_inc"], 1.56,
                                     "incumbent BUY picks the NEAREST clearing "
                                     "level; rr should sit at the padded floor")
                self.assertGreaterEqual(rec["rr_sym"], rec["rr_inc"],
                                        f"{leg}/{rec['index']}: furthest >= "
                                        "nearest by construction")

    def test_b161_census_is_not_vacuous(self):
        led = _load(CENSUS_PATH)
        total = sum(r["n_bound"] for r in led["legs"].values())
        self.assertGreaterEqual(total, 50,
                                "the census found no binding events at all — "
                                "it cannot certify 'rare' while being empty")


class TestB161IncumbentAsymmetryPinned(unittest.TestCase):
    """The geometry decision itself: BUY=min, SELL=max, in the shipped code.
    A future 'tidy symmetry fix' without a >=3-leg funnel verdict fails here
    with a pointer to the evidence, instead of silently moving the funnel."""

    def _reanchor_src(self):
        with open(os.path.join(_ROOT, "engines", "plan.py")) as fh:
            tree = ast.parse(fh.read())
        return next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "_reanchor_blueprint")

    def _picks(self):
        """Map each branch's side ("SELL" from the `if`, "BUY" from its else) to
        the max/min aggregator used to choose the tp candidate from `cands`."""
        fn = self._reanchor_src()
        out = {}
        for node in ast.walk(fn):
            if not (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                    and isinstance(node.test.left, ast.Name)
                    and node.test.left.id == "side"):
                continue
            comps = [c for c in node.test.comparators
                     if isinstance(c, ast.Constant) and isinstance(c.value, str)]
            if not comps:
                continue
            for side, body_nodes in ((comps[0].value, node.body), ("BUY", node.orelse)):
                for stmt in body_nodes:
                    for call in ast.walk(stmt):
                        if (isinstance(call, ast.Call)
                                and isinstance(call.func, ast.Name)
                                and call.func.id in ("max", "min")
                                and "stop_dist" in ast.dump(call)):
                            out[side] = call.func.id
        self.assertEqual(set(out), {"BUY", "SELL"},
                         f"could not locate both side picks, found {out}")
        return out

    def test_b161_buy_picks_nearest_sell_picks_furthest(self):
        picks = dict(self._picks())
        self.assertEqual(picks.get("SELL"), "max",
                         "SELL's furthest-pick is untouched by the b160/b161 "
                         "question; if it moved, the A/B arms no longer match "
                         "production")
        self.assertEqual(picks.get("BUY"), "min",
                         "BUY nearest-pick changed WITHOUT a >=3-leg funnel "
                         "verdict. b161 retired the question CLOSED BY "
                         "EVIDENCE (data/backtest/b161_reanchor_symmetry_"
                         "verdict.json): symmetric is better on 0/5 legs. "
                         "Re-measure first, only then update this pin.")

    def test_b161_docstring_no_longer_promise_the_wrong_thing(self):
        doc = ast.get_docstring(self._reanchor_src()) or ""
        self.assertNotIn("pick the furthest valid target", doc,
                         "the docstring still promises furthest-for-both while "
                         "the code is asymmetric — that contradiction is what "
                         "filed b160")
        self.assertIn("NEAREST", doc)
        self.assertIn("b161", doc.lower(),
                      "the docstring must carry the evidence pointer so the "
                      "next reader retires, not 'fixes', this")


class TestB161AntiVacuity(unittest.TestCase):
    """The two arms must produce different targets on a blueprint where BOTH
    natural candidates clear the floor — otherwise 'dormant' would be a tautology
    of a pick that can never differ."""

    def _bp(self):
        return {"side": "BUY", "entry_price": 100.0, "sl": 99.0,
                "tp_levels": [101.6, 103.0], "tp_shares": [0.5, 0.5]}

    def test_b161_arms_differ_on_the_synthetic_blueprint(self):
        from scripts import b160_reanchor_symmetry_ab as b160
        # min_rr must sit at the live funnel floor (REANCHOR_MIN_RR); the
        # arms were measured with it, so the fixture pins that fact too.
        self.assertEqual(plan_mod.REANCHOR_MIN_RR, 1.5)
        inc = plan_mod._reanchor_blueprint(self._bp(), 100.0, 1.0)
        sym = b160.symmetric_reanchor(self._bp(), 100.0, 1.0)
        self.assertEqual(inc["tp"], 101.6)    # nearest clearing level wins
        self.assertEqual(sym["tp"], 103.0)    # furthest clearing level wins
        self.assertNotEqual(inc["tp"], sym["tp"])
        # and the shipped function IS the incumbent the arms were measured on
        self.assertIs(b160._ORIG_REANCHOR, plan_mod._reanchor_blueprint)

    def test_b161_w1_probe_matches_the_verdict(self):
        probe = _load(W1PROBE_PATH)
        led = _load(VERDICT_PATH)
        self.assertEqual(probe["n_incumbent"],
                         led["legs"]["W1"]["incumbent"]["trades"])
        self.assertEqual(probe["n_symmetric"],
                         led["legs"]["W1"]["symmetric"]["trades"])
        self.assertEqual(probe["differing_common"][0]["entry_index"], 2984)


if __name__ == "__main__":
    unittest.main()
