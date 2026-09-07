"""b130 — THE LAB'S TIME EXIT AND LIVE'S TIME EXIT ARE NOT THE SAME GUARD.

b129 closed with the headline "the live 36h exit is INERT: ts_0 differs from
the incumbent by 0.000R on all seven legs, holds_over_time_exit is 0
everywhere", and its own note filed the caveat this round executes: the lab
counts BAR age while engines/legacy_guards.evaluate_time_exit counts WALL-CLK
hours, and XAUUSD bars do not span the weekend, so the two are different rules
(b130 half (a)). This round measures the SAME grid on BOTH clocks and shows the
inertness is an artefact of the clock, not a property of the guard.

WHAT THE SHIPPED LEDGER SAYS (read out of
data/backtest/b130_wall_clock_parity.json by these tests, never restated):

1. THE GUARD BINDS ON LIVE'S CLOCK. The off-arm census finds 32 trades across
   the seven legs whose WALL age reaches 36h while NONE of them reaches 144
   BARS (max bar age 49..112, max wall age 54..78h). b129's "never once closed
   a funnel trade" is true only in bar time; on the clock live actually runs,
   the guard touches ~2.6% of funnel trades.
2. THE INCUMBENT'S OWN exp_R MOVES WITH THE CLOCK: wall-36h minus bar-144 is
   -0.014..+0.007R per leg (mean +0.002R) — still noise-level under b119's
   0.10R ceiling, so the VALUE 36h stands, but the EVIDENCE behind "inert" did
   not, and a retune decided on the bar clock would have been decided on a
   rule nobody runs.
3. B57'S DIRECTION SURVIVES THE CLOCK CHANGE: a 2h exit loses on 5 of 6 real
   windows on the wall clock too (-0.056..+0.010, mean -0.030R vs the bar
   clock's -0.031R).
4. HALF (b) OF THE ITEM — the neutrality rows now carry n_nonzero NEXT TO the
   flag, and the wall grid is exactly the shape b129's strict floor was built
   for: ts_0h is inert on both clocks (0 non-zero legs), so a proportion-only
   rule would have nothing to say, while ts_36h's one-sided flag rests on
   5 non-zero legs out of 6 windows.

THE ENGINE DIAL: backtest_ohlc gains time_stop_hours (default 0.0 = OFF).
Every pre-b130 call site is byte-identical — pinned by re-running the b129
incumbent cell through the patched engine and requiring the frozen row.

NOTHING IS WIRED: engines/legacy_guards.py untouched, MAX_POSITION_AGE_HOURS
still 36, and a live time-stop retune remains a human gate (b89 class).
"""
from __future__ import annotations

import importlib.util
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "data", "backtest", "b130_wall_clock_parity.json")
LEDGER_129 = os.path.join(ROOT, "data", "backtest",
                          "b129_timestop_reprice.json")


def _load(path):
    with open(path) as f:
        return json.load(f)


_led = lambda: _load(LEDGER)

LEGS = ("cached", "W1", "W2", "W3", "W4", "W5", "W6")
WINDOWS = tuple(w for w in LEGS if w != "cached")


def _script():
    spec = importlib.util.spec_from_file_location(
        "b130_wall_clock_parity",
        os.path.join(ROOT, "scripts", "b130_wall_clock_parity.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestB130LedgerShape(unittest.TestCase):
    def test_ledger_carries_both_clock_grids_on_seven_legs(self):
        led = _led()
        self.assertEqual(led["_legs"], list(LEGS))
        self.assertEqual(len(led["_grid"]["cached"]), 28)   # 2 gates x 14 arms
        for leg in LEGS:
            self.assertEqual(led[leg]["_time_stop_bars"], 144,
                             "the bar incumbent must be live's 36h on M15")
            self.assertGreater(led[leg]["_wall_hours_span"], 144 * 0.25,
                               "a leg must span more than the limit in wall "
                               "hours or the wall clock cannot be tested on it")

    def test_the_live_guard_value_is_imported_not_restated(self):
        """The wall grid's top arm IS MAX_POSITION_AGE_HOURS (b71's rule)."""
        from engines.legacy_guards import MAX_POSITION_AGE_HOURS
        led = _led()
        self.assertIn(float(MAX_POSITION_AGE_HOURS), led["_wall_grid_hours"])
        self.assertEqual(led["_incumbent_wall"],
                         f"no_partial::wall::ts_{MAX_POSITION_AGE_HOURS}h")


class TestB130Integrity(unittest.TestCase):
    def test_every_integrity_claim_holds(self):
        """The bar incumbent must still be b129/b123/b121's frozen trade, and
        'no exit' must be the same trade on both clocks — otherwise the two
        grids are two spliced funnels and no gap below is a clock gap."""
        led = _led()
        for leg in LEGS:
            self.assertTrue(all(led["_integrity"][leg].values()),
                            f"{leg}: {led['_integrity'][leg]}")

    def test_b130_the_bar_incumbent_reproduces_b129_after_the_engine_edit(self):
        """The engine gained a dial mid-flight; b129's frozen incumbent cell
        must be byte-identical, which is the cheap proof the edit is inert at
        its default (pinned by name so a future default flip fails loudly)."""
        led, l129 = _led(), _load(LEDGER_129)
        for leg in LEGS:
            self.assertEqual(
                led[leg]["grid"]["no_partial::bar::ts_144"],
                l129[leg]["grid"]["no_partial::ts_144"],
                f"{leg}: the patched engine moved b129's incumbent")


class TestB130CensusIsClockDependent(unittest.TestCase):
    """Finding 1: the guard is NOT inert on the clock live runs it on."""

    def test_b130_the_wall_clock_binds_where_the_bar_clock_never_does(self):
        led = _led()
        tot_wall = tot_bar = 0
        for leg in LEGS:
            c = led[leg]["_census"]
            tot_wall += c["n_over_wall"]
            tot_bar += c["n_over_bar"]
            self.assertGreaterEqual(c["n_over_wall"], 2, leg)
            self.assertLessEqual(c["max_bar_age"], 143,
                                 f"{leg}: a bar age at/over 144 would make the "
                                 "bar clock bind too and void the contrast")
        self.assertEqual(tot_bar, 0,
                         "b129's zero must stay zero in bar time")
        self.assertGreaterEqual(tot_wall, 25,
                                "the wall census must find a real population")

    def test_the_wall_only_trades_are_named_not_aggregated(self):
        """Anti-vacuity: the census lists the actual trades (age on both
        clocks, exit reason, pnl) so a reader can see a 12-bar trade that is
        52 wall hours old, not just a count."""
        led = _led()
        w4 = led["W4"]["_census"]["wall_only"]
        self.assertEqual(len(w4), led["W4"]["_census"]["n_wall_only"])
        for a in w4:
            self.assertGreaterEqual(a["wall_age_h"], 36.0)
            self.assertLess(a["bar_age"], 144)
        self.assertTrue(any(a["exit_reason"] == "tp1_full" for a in w4),
                        "the tail is not all losers — the guard would also "
                        "cut winners' runners, which is why the sign is mixed")

    def test_b130_the_inert_claim_fails_on_the_wall_clock(self):
        led = _led()
        self.assertFalse(led["_verdict"]["b129_inert_claim_holds_on_wall_clock"],
                         "if off == incumbent on the wall clock too, this "
                         "round's founding claim is dead and must be re-filed")


class TestB130Verdicts(unittest.TestCase):
    def test_the_incumbent_moves_only_noise_level_across_clocks(self):
        """Finding 2: the VALUE 36h stands — |wall - bar| at the live limit is
        under b119's 0.10R ceiling on every leg — even though the inertness
        story did not."""
        led = _led()
        d = led["_verdict"]["wall_minus_bar_at_live_limit_R"]
        for leg in LEGS:
            self.assertLess(abs(d[leg]), 0.10, leg)

    def test_b57_direction_survives_the_clock_change(self):
        """A 2h exit loses one-sidedly on the wall clock too (mean within
        0.01R of the bar clock's -0.031R): the clock changes the census, not
        the ranking."""
        led = _led()
        n2 = led["_neutrality"]["no_partial::wall::ts_2h"]
        self.assertTrue(n2["one_sided"])
        self.assertTrue(n2["unanimous"])
        self.assertLess(n2["mean_R"], 0)
        self.assertGreaterEqual(n2["negative"], 5)
        self.assertLess(abs(n2["mean_R"] - (-0.0305)), 0.01)

    def test_no_wall_arm_earns_a_lever(self):
        """Every one-sided wall arm is under b119's 0.10R ceiling — the round
        re-prices the EVIDENCE, it does not nominate a new guard value."""
        led = _led()
        armed = [n for n, v in led["_neutrality"].items()
                 if n.startswith("no_partial::wall::") and v["one_sided"]]
        self.assertTrue(armed)
        for n in armed:
            self.assertLess(abs(led["_neutrality"][n]["mean_R"]), 0.10, n)


class TestB130NonzeroDenominator(unittest.TestCase):
    """Half (b) of the item: flags must ship with their denominator."""

    def test_b130_every_neutrality_row_reports_n_nonzero_next_to_the_flag(self):
        led = _led()
        for name, v in led["_neutrality"].items():
            self.assertIn("n_nonzero", v, name)
            self.assertEqual(v["n_nonzero"], v["positive"] + v["negative"], name)

    def test_an_inert_arm_has_zero_evidence_and_no_flag(self):
        """ts_0h is byte-identical to the reference on every window: the
        denominator is 0, so BOTH predicates must say nothing."""
        led = _led()
        v = led["_neutrality"]["no_partial::wall::ts_0h"]
        self.assertEqual(v["n_nonzero"], 0)
        self.assertFalse(v["one_sided"])
        self.assertFalse(v["unanimous"])

    def test_the_wall_incumbent_flag_rest_on_real_evidence(self):
        v = _led()["_neutrality"]["no_partial::wall::ts_36h"]
        self.assertTrue(v["one_sided"])
        self.assertGreaterEqual(v["n_nonzero"], 3,
                                "a one-sided flag with <3 non-zero legs is "
                                "exactly the b130 vacuity shape")


class TestB130EngineDialIsInertByDefault(unittest.TestCase):
    """The new dial must not move anything that does not ask for it."""

    def test_the_default_is_off_and_the_signature_is_additive(self):
        import inspect
        from engines.backtest import backtest_ohlc
        sig = inspect.signature(backtest_ohlc)
        self.assertEqual(sig.parameters["time_stop_hours"].default, 0.0)

    def test_wall_off_equals_bar_off_on_a_synthetic_gap(self):
        """A bar series with a weekend hole: the wall clock must close a trade
        the bar clock lets run, and with the dial off both must be identical."""
        from engines.backtest import backtest_ohlc
        day = 86400
        rows = []
        t0 = 1_700_000_000
        # 3 bars, a 3-day gap (weekend), 40 more flat bars
        for i in range(43):
            t = t0 + i * 900 + (day * 3 if i >= 3 else 0)
            rows.append({"time": t, "open": 100.0, "high": 100.5,
                         "low": 99.5, "close": 100.0})

        def fn(row):
            if row["time"] != rows[0]["time"]:
                return None
            return {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 103.0,
                    "grade": "A", "style": "test"}

        off = backtest_ohlc(rows, fn)
        bar = backtest_ohlc(rows, fn, time_stop_bars=144)
        wall = backtest_ohlc(rows, fn, time_stop_hours=36)
        self.assertEqual(off, bar, "144 bars never elapsed; bar clock must not bite")
        self.assertNotEqual(off, wall, "36 wall hours DID elapse across the gap")
        self.assertEqual(off["trade_log"][0]["exit_reason"], "tp")
        self.assertEqual(wall["trade_log"][0]["exit_reason"], "time")
        self.assertLess(off["trade_log"][0]["entry_index"],
                        wall["trade_log"][0]["exit_index"])

    def test_trade_log_shape_is_unchanged_by_the_entry_time_field(self):
        """b121's lesson applied to this round's own engine edit: the new
        internal field must not leak into the frozen trade_log keys."""
        led = _led()
        keys = set(led["cached"]["grid"]["no_partial::bar::ts_144"].keys())
        self.assertEqual(keys, {"trades", "exp_R", "WR%", "avg_win_R",
                                "avg_loss_R", "net_R", "maxDD_R",
                                "mean_hold_bars", "p95_hold_bars",
                                "max_hold_bars", "holds_over_time_exit"})


class TestB130NothingIsWired(unittest.TestCase):
    def test_the_live_guard_and_its_callers_are_untouched(self):
        from engines.legacy_guards import MAX_POSITION_AGE_HOURS
        self.assertEqual(MAX_POSITION_AGE_HOURS, 36)
        src = open(os.path.join(ROOT, "engines", "legacy_guards.py")).read()
        self.assertNotIn("b130", src,
                         "the live guard module must not learn about the lab round")

    def test_no_live_module_imports_this_round(self):
        for f in ("hermes_master.py", "hermes_runtime.py",
                  "position_daemon.py", "signal_daemon.py"):
            p = os.path.join(ROOT, f)
            if os.path.exists(p):
                self.assertNotIn("b130_wall_clock", open(p).read(),
                                 f"{f} imports the b130 lab round")


class TestB130ProducerIsPure(unittest.TestCase):
    """b128's rule: derived blocks are pure functions of the ledger, so b127
    can re-execute them against the frozen artifact."""

    def test_verdict_and_census_reproduce_from_the_shipped_ledger(self):
        m = _script()
        led = _led()
        self.assertEqual(m.verdict(led), led["_verdict"])
        for leg in LEGS:
            self.assertEqual(
                m.census(led[leg]["_ages_off"], 144, 36.0),
                led[leg]["_census"], leg)
        self.assertEqual(m.deltas(led, "exp_R"), led["_delta_exp_R"])
        self.assertEqual(m.neutrality(led), led["_neutrality"])
        self.assertEqual(m.clock_gap(led), led["_clock_gap"])


if __name__ == "__main__":
    unittest.main()
