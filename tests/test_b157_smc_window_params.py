"""b157 — the FVG/OB window params in engines/smc.py must stop lying.

Three pins:
  1. the AST pin: no detector in engines/smc.py may declare a parameter that
     never appears in its own body (the b155 dead-arg class, b157's shape);
  2. the behaviour pin: deleting the dead param changed NOTHING — a fixture
     with one ancient unfilled FVG still scores it into bias (the measured
     funnel says honouring the window is one-sidedly WORSE: cached +0.003R,
     W1 -0.033R, W2 -0.078R, W3 -0.023R), so this is a tightening FORBIDDEN
     by the ledger until a human-gated retune re-prices it;
  3. the observability pin: that stale contribution is now STAMPED in every
     plan via context.smc.fvg_scan — anti-vacuity: the census must count the
     stale gap, and a fresh-only fixture must show zero.
"""
from __future__ import annotations

import ast
import inspect
import unittest
from datetime import datetime, timezone


class TestB157DeadParamsGone(unittest.TestCase):
    def test_b157_fvg_and_ob_signatures_have_no_dead_args(self):
        from engines import smc
        fvg = inspect.signature(smc.detect_fair_value_gaps)
        self.assertNotIn("lookback", fvg.parameters,
                         "b157 deleted the unimplemented lookback; a new one "
                         "must ship WITH a measured window (see ledger)")
        ob = inspect.signature(smc.detect_order_blocks)
        self.assertNotIn("atr_mult", ob.parameters)
        self.assertIn("lookback", ob.parameters)  # OB's IS read (avg-body window)

    def test_b157_killzone_overlap_branch_is_gone(self):
        src = inspect.getsource(
            __import__("engines.smc", fromlist=["active_killzone_session"])
            .active_killzone_session)
        self.assertNotIn("london_close", src,
                         "unreachable duplicate-condition branch (b157 item 3)"
                         "; its removal must not be re-introduced by a comment")
        # behaviour: the mapped zones still answer
        from engines.smc import active_killzone_session
        self.assertEqual(active_killzone_session(
            datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc))[0], "london")
        self.assertEqual(active_killzone_session(
            datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc))[0], "london_close")
        self.assertEqual(active_killzone_session(
            datetime(2026, 9, 8, 6, 0, tzinfo=timezone.utc)), ("dead", 0.0))


class TestB157NoDetectorShipsADeadArg(unittest.TestCase):
    """The b155/b157 class as a standing tripwire: every named parameter of
    the PUBLIC DETECTOR functions in engines/smc.py must be READ in the body.

    Scoped to the detectors (b157's own blast radius): private helpers carry
    dead args too (_empty_smc_result(now), _derive_smc_bias(obs/fvgs/swept),
    _compute_smc_signal(structure_phase), compute_ote_zone(direction)) —
    filed as a follow-up todo, and this pin must be WIDENED when it lands."""

    DETECTORS = ("detect_order_blocks", "detect_fair_value_gaps",
                 "detect_liquidity_sweep", "market_structure_phase",
                 "detect_breaker_blocks", "detect_rejection_blocks",
                 "detect_turtle_soup", "detect_volume_imbalance",
                 "compute_session_liquidity", "premium_discount_zone")

    def _dead_args(self):
        import engines.smc as smc
        path = inspect.getfile(smc)
        tree = ast.parse(open(path, encoding="utf-8").read())
        dead = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in self.DETECTORS:
                continue
            args = [a.arg for a in node.args.args]
            src = ast.get_source_segment(open(path, encoding="utf-8").read(), node) or ""
            body = src.split(":", 1)[-1] if ":" in src else src
            used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            used |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            for a in args:
                if a in ("self", "cls"):
                    continue
                if a not in used:
                    dead.append(f"{node.name}({a})")
        return dead

    def test_b157_no_smc_function_ignores_its_own_parameter(self):
        dead = self._dead_args()
        self.assertEqual(dead, [],
                         f"params declared but never read: {dead}")


def _mk_rows(n, start=4000.0, drift=0.05, step=300):
    rows = []
    price = start
    for i in range(n):
        o = price
        c = price + drift
        rows.append({"time": 1700000000 + i * step, "open": o,
                     "high": max(o, c) + 0.2, "low": min(o, c) - 0.2,
                     "close": c, "volume": 10})
        price = c
    return rows


def _with_gap(rows, at, size=5.0):
    """Insert a bullish 3-candle imbalance at index `at`: c3.low > c1.high."""
    i = at
    base = rows[i]["close"]
    for k in range(i, len(rows)):
        rows[k]["open"] += size
        rows[k]["high"] += size
        rows[k]["low"] += size
        rows[k]["close"] += size
    return rows


class TestB157StaleFvgStillScores(unittest.TestCase):
    def _gap_at(self, rows, idx_in_window):
        # a clean 3-candle bullish gap at absolute index `idx_in_window`
        n = len(rows)
        i = idx_in_window
        c1 = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}
        c2 = {"open": 100.5, "high": 107.0, "low": 100.5, "close": 106.5}
        c3 = {"open": 106.5, "high": 108.0, "low": 106.0, "close": 107.0}
        rows[i], rows[i + 1], rows[i + 2] = c1, c2, c3
        # after the gap price must NEVER trade back into 101..106 -> stays unfilled
        for k in range(i + 3, n):
            lo = rows[k]["low"]; hi = rows[k]["high"]; op = rows[k]["open"]
            shift = 107.0 - lo if lo <= 106.0 else 0.0
            rows[k] = {**rows[k], "open": op + shift, "high": hi + shift,
                       "low": lo + shift, "close": rows[k]["close"] + shift}
        return rows

    def test_b157_ancient_gap_outside_20_bars_still_counts_in_bias(self):
        from engines.smc import smc_analyse, detect_fair_value_gaps
        rows = _mk_rows(120, 60.0, 0.05)          # quiet uptrend, no gaps
        rows[0] = {**rows[0], "open": 60.0, "high": 61.0, "low": 59.0, "close": 60.5}
        rows[1] = {**rows[1], "open": 60.5, "high": 67.0, "low": 60.5, "close": 66.5}
        rows[2] = {**rows[2], "open": 66.5, "high": 68.0, "low": 66.0, "close": 67.0}
        for k in range(3, 120):                    # keep price ABOVE 67 -> unfilled
            base = 67.0 + 0.05 * (k - 3)
            rows[k] = {**rows[k], "open": base, "close": base + 0.05,
                       "high": base + 0.25, "low": base - 0.05}
        fv = detect_fair_value_gaps(rows)
        unfilled = [f for f in fv if not f["filled"]]
        self.assertGreaterEqual(len(unfilled), 1, "fixture must contain the gap")
        self.assertLess(unfilled[0]["c3_index"], 100,
                        "the gap must be older than rows[-20:]")
        res = smc_analyse(rows, now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc))
        # the gap is bullish, so a window-honouring build would drop it;
        # the shipped build keeps the scan unbounded on PURPOSE (measured).
        self.assertGreaterEqual(len(res["active_fvgs"]), 1)
        scan = res["fvg_scan"]
        self.assertGreaterEqual(scan["stale_beyond_advertised"], 1,
                                "b157 census must SEE the stale gap")
        self.assertGreaterEqual(scan["oldest_age_bars"], 21)

    def test_b157_fresh_only_fixture_reports_zero_stale(self):
        from engines.smc import _fvg_scan_census
        fresh = [{"c3_index": 118}]                 # 120 rows -> age 2
        c = _fvg_scan_census(fresh, [], n_rows=120, n_h1=0)
        self.assertEqual(c["stale_beyond_advertised"], 0)
        self.assertEqual(c["unfilled"], 1)
        self.assertEqual(c["oldest_age_bars"], 2)
        old = [{"c3_index": 10}]
        c2 = _fvg_scan_census(old, [], n_rows=120, n_h1=0)
        self.assertEqual(c2["stale_beyond_advertised"], 1)
        self.assertEqual(c2["oldest_age_bars"], 110)
        c3 = _fvg_scan_census([], [{"c3_index": 30}], n_rows=120, n_h1=80)
        self.assertEqual(c3["stale_beyond_advertised"], 1,
                         "H1 gaps age against the H1 window (advertised 10)")
        c4 = _fvg_scan_census([], [{"c3_index": 75}], n_rows=120, n_h1=80)
        self.assertEqual(c4["stale_beyond_advertised"], 0)

    def test_b157_empty_result_carries_the_census_key(self):
        from engines.smc import smc_analyse
        r = smc_analyse(_mk_rows(5), now=datetime(2026, 9, 8, 12, 0,
                                                  tzinfo=timezone.utc))
        self.assertIn("fvg_scan", r)


class TestB157LedgerIntegrity(unittest.TestCase):
    """b127's shape: the decision document must be re-derivable and must not
    hide a changed bar."""

    def test_b157_funnel_ledgers_exist_and_incumbent_matches_the_b118_bar(self):
        import json
        import os
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "backtest")
        paths = {"cached": "b157_window_funnel.json", "W1": "b157_window_funnel_w1.json",
                 "W2": "b157_window_funnel_W2.json", "W3": "b157_window_funnel_W3.json"}
        missing = [p for p in paths.values() if not os.path.exists(os.path.join(base, p))]
        self.assertEqual(missing, [],
                         "b157 shipped code but left its evidence behind")
        bars = {}
        for leg, p in paths.items():
            led = json.load(open(os.path.join(base, p)))
            row = led["legs"][leg]
            bars[leg] = (row["incumbent"]["exp_R"], row["windowed"]["exp_R"])
        # incumbent must be THE STORED BAR, not a new funnel (b118 re-baseline)
        self.assertEqual(bars["cached"][0], 0.278)
        self.assertEqual(bars["W1"][0], 0.211)
        # and tightening must be one-sidedly worse (3 real windows agree)
        worse = [l for l in ("W1", "W2", "W3") if bars[l][1] < bars[l][0]]
        self.assertEqual(len(worse), 3, "b157's keep-the-scan call needs 3/3")
