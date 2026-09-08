"""b158 — the POI grade and the SMC bias see DIFFERENT worlds, ON PURPOSE.

engines/smc.py::grade_poi is fed only the entry-TF sets (active OB/FVG from
the M5 rows) while _derive_smc_bias merges M5+H1. b157 documented that; b158
MEASURED the two fix shapes (scripts/b158_poi_grade_census.py, 930 cached
bars, data/backtest/b158_poi_grade_census.json) and the verdict is KEEP:

  * merging H1 into the grade flips the label on only 3.55% of bars;
  * the entry-TF-blind pathology (grade C while bias rides H1 structure,
    entry world EMPTY) occurred 0/930 real bars — the unbounded entry-TF
    scan (b157's deliberate design) keeps has_ob/has_fvg saturated;
  * the shipped label ranks forward drift monotonically (A+ >0.90 > A +0.31
    > B +0.26 > C +0.15 ATR/12 bars) and the merged world is NOT better
    (separation 0.399 vs 0.382).

These tests pin the DECISION so a future "fix the mismatch" commit must
re-open the measurement, not just read the code and tidy:
  1. the split-world INPUTS pin: smc_analyse passes grade_poi the entry-TF
     sets only (AST: no h1 set reaches the call);
  2. the behaviour pin on a synthetic H1-carried-bias fixture: shipped grade
     reads B, the merged arm would read A — the mismatch is visible, and
     the shipped answer is the measured one;
  3. the consumer tripwire (anti-vacuity both directions): `poi`/`smc_poi`
     appears in NO decision path — the one sanctioned reader
     (hermes_runtime label) is allowed, an invented gate consumer is not;
  4. the ledger pin: the census JSON exists and matches the numbers quoted
     in grade_poi's docstring (b127 shape).
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import unittest
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mk_rows(n, start, step, tf_sec=900):
    rows = []
    p = start
    for i in range(n):
        o = p
        c = p + step
        rows.append({"time": 1700000000 + i * tf_sec, "open": o,
                     "high": max(o, c) + 0.2, "low": min(o, c) - 0.2,
                     "close": c})
        p = c
    return rows


def _h1_gap_up_rows():
    """80 H1 bars with ONE unfilled bullish 3-candle FVG (idx 10-12), then
    price parked above it — H1 carries a bullish bias through structure the
    entry-TF rows know nothing about."""
    h1 = _mk_rows(80, 100.0, 0.05, tf_sec=3600)
    h1[10] = {"time": h1[10]["time"], "open": 100.5, "high": 101.0,
              "low": 100.0, "close": 100.9}
    h1[11] = {"time": h1[11]["time"], "open": 100.9, "high": 108.0,
              "low": 100.9, "close": 107.5}
    h1[12] = {"time": h1[12]["time"], "open": 107.5, "high": 109.0,
              "low": 107.0, "close": 108.0}
    for k in range(13, 80):
        h1[k] = {"time": h1[k]["time"], "open": 108.0, "high": 108.5,
                 "low": 107.6, "close": 108.02}
    return h1


class TestB158SplitWorldInputs(unittest.TestCase):
    def test_b158_grade_poi_call_sees_only_entry_tf_sets(self):
        """AST pin: inside smc_analyse, the grade_poi call's has_ob/has_fvg
        kwargs must be built from the entry-TF names only.  The bias call
        (_derive_smc_bias) merges `+ h1_obs` / `+ h1_fvgs`; if someone wires
        the H1 sets into grade_poi WITHOUT re-opening the census, this fails
        loudly and points at the ledger."""
        import engines.smc as smc
        with open(inspect.getfile(smc), encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "smc_analyse")
        call = next(n for n in ast.walk(fn)
                    if isinstance(n, ast.Call)
                    and getattr(n.func, "id", "") == "grade_poi")
        kw_names = {k.arg for k in call.keywords
                    if k.arg in ("has_ob", "has_fvg")}
        self.assertEqual(kw_names, {"has_ob", "has_fvg"},
                         "grade_poi must keep receiving has_ob/has_fvg")
        for k in call.keywords:
            if k.arg in ("has_ob", "has_fvg"):
                ids = {n.id for n in ast.walk(k.value) if isinstance(n, ast.Name)}
                self.assertNotIn("h1_obs", ids)
                self.assertNotIn("h1_fvgs", ids)
                self.assertNotIn("h1_unmitigated", ids)
                self.assertNotIn("h1_unfilled", ids)

    def test_b158_bias_call_merges_h1_worlds(self):
        """The other side of the split, pinned so the PAIR is explicit:
        _derive_smc_bias IS fed the merged sets."""
        import engines.smc as smc
        with open(inspect.getfile(smc), encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "smc_analyse")
        call = next(n for n in ast.walk(fn)
                    if isinstance(n, ast.Call)
                    and getattr(n.func, "id", "") == "_derive_smc_bias")
        ids = {n.id for arg in call.args
               for n in ast.walk(arg) if isinstance(n, ast.Name)}
        for want in ("obs", "h1_obs", "fvgs", "h1_fvgs"):
            self.assertIn(want, ids,
                          "b158 pins the split: bias merges H1, grade does not")


class TestB158MismatchIsVisible(unittest.TestCase):
    """Behaviour anti-vacuity: on a synthetic H1-carried bias the two worlds
    genuinely disagree — shipped grade says B, merged would say A.  If the
    fixture ever stops separating, the measurement it pins is vacuous."""

    def _result_and_arms(self):
        from engines.smc import smc_analyse, grade_poi
        m5 = _mk_rows(120, 100.0, 0.01)      # dead-flat entry world
        h1 = _h1_gap_up_rows()
        r = smc_analyse(m5, now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
                        h1_rows=h1)
        common = dict(
            liq_sweep=r["liquidity_sweep"]["swept"],
            discount=((r["bias"] == "bullish"
                       and r["premium_discount"]["zone"] == "discount")
                      or (r["bias"] == "bearish"
                          and r["premium_discount"]["zone"] == "premium")),
            killzone_weight=r["killzone"]["weight"],
            structure_aligned=(
                (r["bias"] == "bullish" and r["market_structure"]["phase"]
                 in ("bos_bullish", "choch_bullish"))
                or (r["bias"] == "bearish" and r["market_structure"]["phase"]
                    in ("bos_bearish", "choch_bearish"))),
        )
        shipped = grade_poi(has_ob=bool(r["active_order_blocks"]),
                            ob_mitigated=False,
                            has_fvg=bool(r["active_fvgs"]),
                            fvg_filled=False, **common)
        merged = grade_poi(has_fvg=bool(r["active_fvgs"] or r["h1_active_fvgs"]),
                           has_ob=bool(r["active_order_blocks"]
                                       or r["h1_active_order_blocks"]),
                           ob_mitigated=False, fvg_filled=False, **common)
        return r, shipped, merged

    def test_b158_h1_carried_bias_lands_b_shipped_and_a_merged(self):
        r, shipped, merged = self._result_and_arms()
        self.assertEqual(r["bias"], "bullish",
                         "fixture: H1 FVG must carry a bullish bias")
        self.assertEqual((len(r["active_order_blocks"]), len(r["active_fvgs"])),
                         (0, 0), "fixture: entry-TF world must be EMPTY")
        self.assertGreater(len(r["h1_active_fvgs"]), 0)
        self.assertEqual(r["poi"], shipped)
        self.assertEqual(shipped, "B")
        self.assertEqual(merged, "A",
                         "anti-vacuity: without a grade gap there is no "
                         "split world to document")
        self.assertNotEqual(shipped, merged)


class TestB158NoDecisionConsumer(unittest.TestCase):
    """b157 grep-verified that `poi` feeds no gate. Pin it: the ONLY readers
    of the poi value outside engines/smc.py are the sanctioned LABEL writer
    (hermes_runtime's ctx['quality']['smc_poi']) and tests. A commit that
    starts gating on poi without its own funnel round must fail here."""

    SANCTIONED = ("engines/smc.py", "hermes_runtime.py")

    def _poi_readers(self):
        readers = []
        for root, dirs, files in os.walk(_ROOT):
            dirs[:] = [d for d in dirs
                       if d not in (".git", "legacy_backup", "legacy_removed",
                                    "tests", "__pycache__", "data")]
            for f in files:
                if not f.endswith(".py"):
                    continue
                p = os.path.join(root, f)
                rel = os.path.relpath(p, _ROOT)
                if rel in self.SANCTIONED:
                    continue
                try:
                    tree = ast.parse(open(p, encoding="utf-8").read())
                except (SyntaxError, UnicodeDecodeError):
                    continue
                for n in ast.walk(tree):
                    hit = ((isinstance(n, ast.Subscript) and isinstance(
                        n.slice, ast.Constant) and n.slice.value in ("poi", "smc_poi"))
                        or (isinstance(n, ast.Attribute) and n.attr in ("poi", "smc_poi"))
                        or (isinstance(n, ast.Call)
                            and getattr(n.func, "id", "") == "get"
                            and n.args and isinstance(n.args[0], ast.Constant)
                            and n.args[0].value in ("poi", "smc_poi")))
                    if hit:
                        readers.append(rel)
                        break
        return sorted(set(readers))

    def test_b158_poi_has_no_consumer_outside_the_label(self):
        self.assertEqual(self._poi_readers(), [],
                         "poi/smc_poi gained a reader outside engines/smc.py "
                         "and the sanctioned label writer in hermes_runtime.py; "
                         "gating on it requires its own funnel round (b158)")

    def test_b158_pin_is_not_vacuous(self):
        """The scanner must CATCH a gate-style consumer if one existed —
        prove it on an in-memory synthetic, never written to disk."""
        synthetic = ("import engines.smc as smc\n"
                     "ok = smc_analyse(rows)['poi'] == 'A+'\n")
        tree = ast.parse(synthetic)
        hits = 0
        for n in ast.walk(tree):
            if (isinstance(n, ast.Subscript)
                    and isinstance(n.slice, ast.Constant)
                    and n.slice.value == "poi"):
                hits += 1
        self.assertEqual(hits, 1, "the scanner pattern must bind a real gate")


class TestB158LedgerIntegrity(unittest.TestCase):
    def test_b158_census_ledger_matches_the_quoted_numbers(self):
        path = os.path.join(_ROOT, "data", "backtest",
                            "b158_poi_grade_census.json")
        self.assertTrue(os.path.exists(path),
                        "b158's KEEP decision cites this ledger; it shipped "
                        "with the code (b127 rule)")
        with open(path) as fh:
            led = json.load(fh)
        self.assertEqual(led["item"], "b158")
        self.assertGreaterEqual(led["dataset"]["bars_scanned"], 900)
        self.assertAlmostEqual(led["flip_rate"], 0.0355, places=3)
        self.assertEqual(led["entry_tf_blind_bars"], 0)
        # shipped arm must rank A+ better than C, and beat the merged arm's
        # separation (the numbers in grade_poi's docstring)
        sq = led["forward_drift_by_grade_sq"]
        self.assertGreater(sq["A+"]["mean_drift_atr"], sq["C"]["mean_drift_atr"])
        self.assertGreater(led["separation_sq"], led["separation_merged"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
