"""b92 — the cooldown gate ledger (b87 queue item 3).

Pins the three facts this round shipped, each in the domain that can actually
measure it:

  1. BOOK DOMAIN: every cached/confirm leg is weekday-only (0 Sunday bars), so
     the post_open window (Sun 23:00->23:15 UTC) contains ZERO funnel signals
     on all 5 legs. The b84/b86/b88 kept/dropped-book template CANNOT price
     this gate — a "0 kills" reading here would be a measurement-medium
     artifact, not a no-op verdict like b86's range-kill. The ledger must say
     book_can_price_this_gate: false.
  2. CLOCK DOMAIN: the restart clause is process-lifetime state; the only
     honest medium is the live master-cycle log (plan_history created_at).
     The gap rule (>= 30 min = real restart = guard armed) is the b30 fix,
     pinned here so a future refactor of ensure_startup_cooldown trips this
     test instead of silently changing what "armed" means.
  3. SHADOW DOMAIN (b87's question): market_hours ALLOWS Sun 23:00-23:14, so
     cooldown is the ONLY gate on its window — the opposite of b86's
     fully-shadowed range-kill. If someone ever moves market open earlier than
     23:00 UTC or extends market_hours to cover the first 15 min, this row
     flips to SHADOWED and the redundancy conversation re-opens.

Plus the standard lab hygiene: the shipped JSON exists with the verdict block,
the gate constants match the live module (imported, never restated), and no
live-path module imports the lab script.
"""
from __future__ import annotations

import datetime as dt
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "data" / "backtest" / "b92_cooldown_gate.json"

import sys
sys.path.insert(0, str(REPO))

from engines import cooldown as cd                     # noqa: E402  (live module)


def _led():
    with open(LEDGER, encoding="utf-8") as f:
        return json.load(f)


class TestShippedLedger(unittest.TestCase):
    def test_ledger_exists_with_verdict(self):
        self.assertTrue(LEDGER.exists(),
                        "b92 ledger missing — run scripts/b92_cooldown_gate.py")
        v = _led()["_verdict"]
        for k in ("legs", "sunday_bars_total", "signals_in_window_total",
                  "book_can_price_this_gate", "restart_arms_in_live_record",
                  "shadow_verdict", "adaptive_reachable"):
            self.assertIn(k, v)

    def test_five_legs_all_weekday_only(self):
        led = _led()
        self.assertEqual(led["_verdict"]["legs"], 5)
        for leg in ("cached", "W1", "W2", "W3", "W4"):
            L = led[leg]
            self.assertEqual(L["_sunday_bars"], 0,
                             f"{leg}: dataset suddenly contains Sunday bars — "
                             "the book CAN price the gate now, re-measure")
            self.assertEqual(L["_signals_in_post_open_window"], 0)
            self.assertFalse(L["bind"]["book_is_measurable"])
        self.assertFalse(led["_verdict"]["book_can_price_this_gate"])

    def test_constants_match_live_module(self):
        """b82 discipline: the ledger must carry the LIVE constants, imported."""
        led = _led()
        self.assertEqual(led["_live_gates"]["POST_OPEN_COOLDOWN_MIN"],
                         cd.POST_OPEN_COOLDOWN_MIN)
        self.assertEqual(led["_live_gates"]["RESTART_COOLDOWN_MIN"],
                         cd.RESTART_COOLDOWN_MIN)
        self.assertEqual(led["reachability"]["constants"]
                         ["POST_OPEN_COOLDOWN_MIN"], cd.POST_OPEN_COOLDOWN_MIN)


class TestPostOpenPredicate(unittest.TestCase):
    """The window boundary itself, replayed from the ledger's own predicate
    shape (b52 anti-vacuity: both directions)."""

    def test_boundaries(self):
        sun = dt.datetime(2026, 8, 30, 23, 0, tzinfo=dt.timezone.utc)
        self.assertTrue(cd._market_open_utc(sun) == sun)
        for m in (0, 5, 14):
            t = sun + dt.timedelta(minutes=m)
            self.assertTrue(_in_window(t), f"{t} must be inside the guard")
        for m in (15, 20, 60):
            t = sun + dt.timedelta(minutes=m)
            self.assertFalse(_in_window(t), f"{t} must be past the guard")
        # a mid-week bar is never in the window (the datasets' whole shape)
        self.assertFalse(_in_window(dt.datetime(2026, 8, 26, 12, 0,
                                               tzinfo=dt.timezone.utc)))

    def test_market_hours_allows_the_guard_window(self):
        """The shadow row: market_hours must NOT cover the window, or the
        cooldown gate becomes redundant (b87 flips to SHADOWED)."""
        from engines.market_hours import is_market_open
        sun = dt.datetime(2026, 8, 30, 23, 0, tzinfo=dt.timezone.utc)
        for m in (0, 5, 10, 14):
            t = sun + dt.timedelta(minutes=m)
            self.assertTrue(is_market_open(t),
                            f"market_hours now blocks {t} — cooldown's window "
                            "is shadowed; re-run the b87 redundancy row")
            self.assertTrue(_in_window(t))


class TestClockDomain(unittest.TestCase):
    def test_restart_gap_rule_is_the_b30_rule(self):
        """ensure_startup_cooldown arms on a gap >= 30 min; the ledger's
        live-cycle probe uses the same threshold — pin them together."""
        led = _led()
        self.assertEqual(led["_live_gates"]["restart_gap_min"], 30)
        lc = led["live_cycles"]
        self.assertGreater(lc["cycles"], 500,
                           "plan_history too thin to say anything about the "
                           "restart clause — re-measure after more live days")
        for g in lc["gaps"]:
            self.assertGreaterEqual(g["gap_min"], 30)
        # arms counted FROM the gaps list, never restated
        self.assertEqual(lc["restart_guard_armed"], len(lc["gaps"]))

    def test_reach_is_analytic(self):
        led = _led()
        r = led["reach"]
        self.assertEqual(r["window_min"], cd.POST_OPEN_COOLDOWN_MIN)
        # Sun 23:00 -> Fri 22:00 = 117 h
        self.assertEqual(r["session_min_per_week"], 117 * 60)
        self.assertAlmostEqual(r["share_of_trading_time"],
                               cd.POST_OPEN_COOLDOWN_MIN / (117 * 60), places=5)


class TestShadowVerdict(unittest.TestCase):
    def test_not_shadowed(self):
        led = _led()
        s = led["shadow"]
        self.assertEqual(s["shadowed_by_market_hours"], 0)
        self.assertGreaterEqual(s["covered_only_by_cooldown"], 1)
        self.assertIn("NOT_SHADOWED", s["verdict"])

    def test_adaptive_unreachable(self):
        """b86's REACHABILITY row: learning.py cannot move either knob."""
        led = _led()
        self.assertFalse(led["_verdict"]["adaptive_reachable"])
        from engines.learning import adjustments
        changes = (adjustments().get("changes") or {})
        self.assertNotIn("cooldown", " ".join(changes.keys()).lower())


def _in_window(t: dt.datetime) -> bool:
    """Same predicate the ledger script uses (kept tiny on purpose — the
    script imports cd._market_open_utc, this mirrors it)."""
    opened = cd._market_open_utc(t)
    return t < opened + dt.timedelta(minutes=cd.POST_OPEN_COOLDOWN_MIN)


class TestLabHygiene(unittest.TestCase):
    def test_no_live_module_imports_the_lab_script(self):
        for base in ("engines", "notifier"):
            for p in (REPO / base).rglob("*.py"):
                if p.name == "b92_cooldown_gate.py":
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("b92_cooldown_gate", text,
                                 f"live-path module {p} imports the lab script")

    def test_script_does_not_touch_gates(self):
        """Hard-rule tripwire: the lab script must not reassign any live
        constant (it measures, never mutates)."""
        src = (REPO / "scripts" / "b92_cooldown_gate.py").read_text(
            encoding="utf-8")
        for bad in ("POST_OPEN_COOLDOWN_MIN =", "RESTART_COOLDOWN_MIN =",
                    "MIN_RISK_REWARD =", "MIN_SETUP_GRADE ="):
            self.assertNotIn(bad, src,
                             f"lab script mutates a live gate: {bad}")


if __name__ == "__main__":
    unittest.main()
