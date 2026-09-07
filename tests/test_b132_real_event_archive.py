"""b132 — THE NEWS VETO PRICED ON A REAL HISTORICAL EVENT CALENDAR.

b131 built the veto machinery and had to report its own premise false: the
only calendar on the box (git union of committed economic_calendar.json)
covers Aug 23..Sep 12 2026, so six of seven legs were COVERAGE ZERO and
"inert" there was an absence of data. b132 recovered a real archive — the
Internet Archive's daily crawl of the SAME ForexFactory feed (95 snapshots,
1941 events, 81 high-impact USD/XAU, span 2026-05-03..2026-09-12) — and
re-priced the veto on it. These tests read the shipped ledger
(data/backtest/b132_news_veto_real_calendar.json) and re-derive its claims
from the archive file itself; nothing here restates a number as a literal
that the ledger can already produce.

WHAT IS PINNED
1. ARCHIVE IS REAL AND IN LIVE'S SHAPE: the fetched archive parses, carries
   high-impact USD events, and every event has the keys
   engines/economic_calendar.py emits (b82's parity rule — the archive must
   be readable by the predicate live runs, not by a private schema).
2. COVERAGE IS RE-DERIVED, NOT QUOTED: coverage() re-run from the archive +
   the leg's own bar span must equal the stored _coverage rows, cached/W1
   covered, W2..W6 honestly NOT (the archive starts 2026-05-03). An
   anti-vacuity probe shows a leg entirely outside the archive reads 0.0.
3. THE VETO REMOVES WINNERS AT LIVE'S WIDTH: the ±30min arm's vetoed entries
   carry POSITIVE R on BOTH covered legs (cached +2.8R, W1 +0.5R); on cached
   that drags exp_R (-0.053) and net_R (-6.0R) down — the guard costs
   measured R on this data, it does not save it. (W1's replacement re-entry
   nearly covers the hole at +0.004 exp_R, so the per-leg claim pinned here
   is the vetoed_R sign, not a uniform delta sign. The veto stays live
   insurance: fail-closed on outage, tail-risk the funnel's short holds
   rarely sample. That is a human-gate argument, not a wiring by this round.)
4. NO ARM IS A LEVER, AND THE CEILING CAN LIE: the ±720/±1440min arms clear
   b119's 0.10R ceiling on exp_R while net_R is NEGATIVE on covered legs —
   pure subtraction inflation. lever_test() must flag both as
   exp_R_inflation_by_subtraction and is_lever=False on every arm. This is
   the reusable rule the round files: an ENTRY-REMOVING arm must be judged
   on net_R, never on exp_R alone.
5. THE REAL CALENDAR MOVED b131'S NUMBER: cached Δexp_R at live width went
   -0.026 (git-union calendar) -> -0.053 (real archive). The synthetic-proxy
   era's answer was not the real one.
6. NOTHING WIRED: live's blackout default and the macro gate's wiring are
   untouched; engines/macro_filter.py and auto_executor Check 7 unchanged.
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "data", "backtest",
                      "b132_news_veto_real_calendar.json")
LEDGER_129 = os.path.join(ROOT, "data", "backtest",
                          "b129_timestop_reprice.json")
ARCHIVE_GLOB = os.path.join(ROOT, "data", "calendar",
                            "events_archive_ff_wayback_*.json")

LEGS = ("cached", "W1", "W2", "W3", "W4", "W5", "W6")


def _load(path):
    with open(path) as f:
        return json.load(f)


def _script():
    spec = importlib.util.spec_from_file_location(
        "b132_news_veto_real_calendar",
        os.path.join(ROOT, "scripts", "b132_news_veto_real_calendar.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_led = lambda: _load(LEDGER)


def _archive():
    paths = sorted(glob.glob(ARCHIVE_GLOB))
    assert paths, "b132's archive must be committed: run scripts/b132_event_archive_fetch.py"
    return _load(paths[-1])


class TestB132ArchiveIsReal(unittest.TestCase):
    def test_b132_archive_shape_matches_the_live_calendar_schema(self):
        cal = _archive()
        self.assertGreaterEqual(cal["n_events"], 1000)
        self.assertGreater(cal["n_high_gold"], 50)
        self.assertEqual(cal["n_snapshots_failed"], 0,
                         "every CDX snapshot must be captured or retried — "
                         "a silent gap is a fake 'no events'")
        # the keys engines/economic_calendar._fetch_forexfactory emits
        want = {"title", "currency", "impact", "date", "time",
                "forecast", "previous"}
        for e in cal["events"][:50]:
            self.assertTrue(want.issubset(e.keys()))
        self.assertTrue(all(e["impact"] in ("high", "medium", "low")
                            for e in cal["events"]))

    def test_b132_coverage_block_re_derives_from_the_archive(self):
        b132, led, cal = _script(), _led(), _archive()
        for leg in LEGS:
            got = b132.coverage(cal, led[leg]["_first"], led[leg]["_last"])
            self.assertEqual(got, led[leg]["_coverage"],
                             f"{leg} coverage row no longer derives from the "
                             "archive — the covered-leg vote is stale")
        self.assertTrue(led["_coverage"]["cached"]["covered"])
        self.assertTrue(led["_coverage"]["W1"]["covered"])
        for leg in ("W2", "W3", "W4", "W5", "W6"):
            self.assertFalse(led["_coverage"][leg]["covered"],
                             f"{leg} is outside the archive span and must "
                             "NOT vote (b131's coverage-zero disease)")
        self.assertEqual(led["_covered_legs"], ["cached", "W1"])

    def test_b132_coverage_is_not_vacuously_true(self):
        b132, cal = _script(), _archive()
        import datetime as dt
        ev = [dt.datetime.fromisoformat(e["date"]).timestamp()
              for e in cal["events"] if e["impact"] == "high"]
        lo, hi = min(ev), max(ev)
        far = {"first": hi + 400 * 86400, "last": hi + 410 * 86400}
        c = b132.coverage(cal, far["first"], far["last"])
        self.assertEqual(c["n_high_events_in_leg"], 0)
        self.assertEqual(c["span_overlap_frac"], 0.0)
        self.assertFalse(c["covered"])


class TestB132VetoPricing(unittest.TestCase):
    def setUp(self):
        self.led = _led()

    def test_off_arm_is_the_frozen_b129_incumbent_on_every_leg(self):
        l129 = _load(LEDGER_129)
        integ = _script().integrity(self.led, l129)
        for leg in LEGS:
            self.assertTrue(integ[leg]["off_matches_b129_incumbent"],
                            f"{leg}: the grid is no longer the same funnel")
        self.assertEqual(self.led["_integrity"], integ)

    def test_b132_the_live_width_veto_removes_winners_not_losses(self):
        arm = self.led["_arms"][1]                      # real::±<live min>
        for leg in self.led["_covered_legs"]:
            cen = self.led["_census"][leg][arm]
            self.assertGreater(cen["n_vetoed_entries"], 0,
                               "a covered leg with zero vetoed entries cannot "
                               "support the finding")
            # THE finding: the entries the veto deletes were themselves
            # WINNERS in R. On cached that also drags exp_R and net_R down;
            # on W1 the re-entered replacement nearly covers the hole
            # (+0.004 exp_R), so only the vetoed_R sign is claimed per-leg.
            self.assertGreater(cen["vetoed_R"], 0,
                               f"{leg}: the vetoed entries' own R was not "
                               "positive — the 'veto costs R' finding changed "
                               "and this note must be re-read, not re-asserted")
        self.assertLess(self.led["_delta_exp_R"][arm]["cached"], 0.0)
        self.assertLess(self.led["_delta_net_R"][arm]["cached"], 0.0)

    def test_b132_no_arm_is_a_lever_and_the_ceiling_cannot_lie(self):
        led = self.led
        self.assertEqual(_script().lever_test(led), led["_lever"])
        for arm, v in led["_lever"].items():
            self.assertFalse(v["is_lever"],
                             f"{arm} now reads as a lever — the veto question "
                             "is re-opened and a human gate must decide")
            if v["exp_R_clears_ceiling"]:
                self.assertTrue(v["exp_R_inflation_by_subtraction"],
                                f"{arm}: exp_R cleared the ceiling while "
                                "net_R did not fall — the subtraction-inflation "
                                "guard went blind")
        cleared = [a for a, v in led["_lever"].items()
                   if v["exp_R_clears_ceiling"]]
        self.assertTrue(cleared, "the grid lost the arms that clear the "
                        "ceiling on exp_R alone; the guard is vacuous")

    def test_b132_derived_blocks_reproduce(self):
        b132, led = _script(), self.led
        self.assertEqual(b132.vetoed_census(led), led["_census"])
        self.assertEqual(b132.deltas(led), led["_delta_exp_R"])
        self.assertEqual(b132.deltas(led, "net_R", 1), led["_delta_net_R"])
        self.assertEqual(b132.deltas(led, "maxDD_R", 1), led["_delta_maxDD_R"])
        self.assertEqual(b132.neutrality(led), led["_neutrality"])
        self.assertEqual(b132.verdict(led), led["_verdict"])

    def test_b132_the_real_calendar_changed_b131s_answer(self):
        v = self.led["_vs_b131"]["cached"]
        self.assertTrue(v["changed"])
        self.assertLess(v["b132_real_archive"], 0.0)
        self.assertNotEqual(v["b131_real_cal"], v["b132_real_archive"])


class TestB132NothingWired(unittest.TestCase):
    def test_b132_live_veto_is_untouched(self):
        import inspect
        from engines.macro_filter import evaluate_macro_filter
        self.assertEqual(_led()["_live_blackout_min"],
                         int(inspect.signature(evaluate_macro_filter)
                             .parameters["blackout_minutes"].default))
        src = open(os.path.join(ROOT, "engines", "auto_executor.py")).read()
        self.assertIn("blocked_by_macro", src,
                      "Check 7 must still honour the macro veto flag")
        # the flag's producer: both live entry paths must still CALL the gate
        for path in ("hermes_runtime.py", "engines/signal_listener.py"):
            s = open(os.path.join(ROOT, path)).read()
            self.assertIn("evaluate_macro_filter", s,
                          f"{path} must still consult the macro gate live")

    def test_b132_name_carrier_archive_is_reproducible_offline(self):
        # the fetcher's pure half must work on a canned payload so the
        # procedure survives a network outage (b127: pin the post-processing,
        # not the crawl).
        b132f = importlib.util.spec_from_file_location(
            "b132_event_archive_fetch",
            os.path.join(ROOT, "scripts", "b132_event_archive_fetch.py"))
        mod = importlib.util.module_from_spec(b132f)
        b132f.loader.exec_module(mod)
        canned = [{"title": "NFP", "country": "USD",
                   "date": "2026-06-05T08:30:00-04:00", "impact": "High",
                   "forecast": "", "previous": ""},
                  {"title": "Nope", "country": "USD", "date": "", "impact": "High"}]
        out = mod.normalise(canned, "20260605000000")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["currency"], "USD")
        self.assertEqual(out[0]["impact"], "high")
        self.assertEqual(out[0]["captured"], "20260605000000")


if __name__ == "__main__":
    unittest.main()
