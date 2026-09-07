"""b132 — THE NEWS VETO PRICED ON A REAL HISTORICAL EVENT CALENDAR.

b131 built the veto machinery and had to report its own premise false: the
only calendar on the box (git union of committed economic_calendar.json)
covers Aug 23..Sep 12 2026, so six of seven legs were COVERAGE ZERO and
"inert" there was an absence of data. b132 recovered a real archive — the
Internet Archive's crawl of the SAME ForexFactory feed — and re-priced the
veto on it. These tests read the shipped ledger
(data/backtest/b132_news_veto_real_calendar.json) and re-derive its claims
from the archive file itself; nothing here restates a number as a literal
that the ledger can already produce.

b133 RE-STATED THIS ROUND'S CLAIMS (the archive got 2.6x deeper)
================================================================
b132's fetcher queried CDX by EXACT url and concluded the archive began
2026-05-03. That was a query artefact: ForexFactory ships the feed with a
cache-busting `?version=<hash>`, and every 2021..2025 crawl recorded the url
WITH that string, so those captures sit under a different urlkey. Re-queried
by prefix, the same feed yields 145 captured days from 2025-01-19 (5043
events, 303 high-impact USD/XAU) instead of 95 days from 2026-05-03 (1941
events). Consequence for the study: ALL SEVEN legs are now covered, so the
covered-leg vote went from n=2 (below b129's strict floor, no strict answer
possible) to n=7 (a strict answer is reachable). The veto question now HAS
one: at live's own ±30min the delta is one-sided NEGATIVE on 4 legs vs 1
positive, mean -0.0094R — the guard costs exp_R, it does not add it, and no
arm is a lever.

WHAT IS PINNED
1. ARCHIVE IS REAL AND IN LIVE'S SHAPE: the fetched archive parses, carries
   high-impact USD events, and every event has the keys
   engines/economic_calendar.py emits (b82's parity rule — the archive must
   be readable by the predicate live runs, not by a private schema).
2. COVERAGE IS RE-DERIVED, NOT QUOTED: coverage() re-run from the archive +
   the leg's own bar span must equal the stored _coverage rows — and now on
   ALL SEVEN legs (b133's point: the coverage-zero disease was a query bug,
   not a data limit). An anti-vacuity probe shows a leg entirely outside the
   archive still reads 0.0, so "covered" is earned, not defaulted.
2a.AN ARCHIVE REGRESSION CANNOT PASS SILENTLY: the depth (>=5000 events) and
   the exact count of payloads Wayback indexes but does not serve (3 x 404)
   are pinned, so a re-fetch that quietly re-narrows the study fails here.
2b.THE ARCHIVE PICKER USES SPAN, NOT FILENAME: the study must price on the
   widest archive. A filename sort puts a later-but-thinner re-fetch last and
   would silently re-narrow the study; _pick_archive() must return the widest
   span even when it sorts first.
3. THE VETO REMOVES WINNERS ON 5 OF 6 EVIDENCE LEGS AT LIVE'S WIDTH: the
   ±30min arm's vetoed entries carry POSITIVE R on cached, W1, W3, W4, W5;
   W6 is the exception (its vetoed entries were -0.53R losers, so there the
   guard helped) and W2 has NO evidence at live width — it is calendar-
   COVERED (12 high events in span) but vetoed ZERO funnel entries, so it
   cannot vote on the sign at all (b133's finding: coverage is not evidence;
   b132's dead-run prose had W2 and W6's roles inverted). On cached the veto
   drags exp_R (-0.053) and net_R (-6.0R) down — the guard costs measured R
   on this data, it does not save it. The pinned claim is the MAJORITY sign
   over legs-with-evidence, not a uniform one: a flipped majority re-opens
   the question. The veto stays live insurance: fail-closed on outage,
   tail-risk the funnel's short holds rarely sample. That is a human-gate
   argument, not a wiring by this round.
4. NO ARM IS A LEVER, AND THE CEILING CAN LIE: the ±720/±1440min arms clear
   b119's 0.10R ceiling on exp_R while net_R is NEGATIVE on covered legs —
   pure subtraction inflation. lever_test() must flag both as
   exp_R_inflation_by_subtraction and is_lever=False on every arm. This is
   the reusable rule the round files: an ENTRY-REMOVING arm must be judged
   on net_R, never on exp_R alone.
5. THE REAL CALENDAR MOVED b131'S NUMBER: cached Δexp_R at live width went
   -0.026 (git-union calendar) -> -0.053 (real archive), and FIVE of seven
   legs changed sign or magnitude once the archive reached back into 2025.
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
    """The WIDEST-span archive on disk — same rule the study uses (b133:
    a filename sort can put a later-but-thinner re-fetch last)."""
    paths = sorted(glob.glob(ARCHIVE_GLOB))
    assert paths, "b132's archive must be committed: run scripts/b132_event_archive_fetch.py"
    return _load(max(paths, key=lambda q: _load(q).get("event_first", "")
                     + "|" + str(_load(q).get("event_last", ""))))


class TestB132ArchiveIsReal(unittest.TestCase):
    def test_b132_archive_shape_matches_the_live_calendar_schema(self):
        cal = _archive()
        self.assertGreaterEqual(cal["n_events"], 5000,
                                "b133 deepened the archive to 2025-01-19; a "
                                "regression to the thin 2026-only crawl must "
                                "not pass silently")
        self.assertGreater(cal["n_high_gold"], 50)
        self.assertEqual(cal["n_snapshots_failed"], 0,
                         "every CDX snapshot must be captured or retried — "
                         "a silent gap is a fake 'no events'")
        self.assertEqual(cal["n_snapshots_unrecoverable"], 3,
                         "the 3 payloads Wayback indexes but 404s on id_ are "
                         "recorded, not hidden — if that number moves, the "
                         "archive was re-fetched and must be re-read")
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
        # b133: the prefix-query fix reached back into 2025, so ALL SEVEN legs
        # now vote. If the archive ever regresses to the thin 2026-only crawl,
        # W2..W6 fall out of _covered_legs and this fails loudly.
        self.assertEqual(led["_covered_legs"], list(LEGS))
        for leg in LEGS:
            self.assertTrue(led["_coverage"][leg]["covered"],
                            f"{leg} dropped out of coverage — the b133 "
                            "archive-depth regression")

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
        pos, neg, silent = [], [], []
        for leg in self.led["_covered_legs"]:
            cen = self.led["_census"][leg][arm]
            if cen["n_vetoed_entries"] == 0:
                silent.append(leg)                      # covered, no evidence
            elif cen["vetoed_R"] > 0:
                pos.append(leg)
            else:
                neg.append(leg)
        # THE b133 finding, honestly: on the DEEP archive the vetoed entries
        # were winners on 5 of the 6 legs that HAVE evidence at live width;
        # W6 is the exception (its 8 vetoed entries were -0.53R losers, so
        # there the guard helped) and W2 cannot vote — it is calendar-covered
        # but the funnel took zero entries inside any ±30min window. Pinning
        # the majority sign over evidence legs, not a uniform one — a flipped
        # majority re-opens the question.
        self.assertEqual(pos, ["cached", "W1", "W3", "W4", "W5"])
        self.assertEqual(neg, ["W6"])
        self.assertEqual(silent, ["W2"])
        self.assertLess(self.led["_delta_exp_R"][arm]["cached"], 0.0)
        self.assertLess(self.led["_delta_net_R"][arm]["cached"], 0.0)

    def test_b133_coverage_is_not_evidence_a_covered_leg_can_vote_zero(self):
        """b133: the ±30min arm is INERT on W2 for a reason the b132 prose
        never anticipated. W2 passes coverage() (12 high-impact events in
        span, overlap 1.0) yet the veto deleted ZERO funnel entries there —
        the events exist and no trade was open near them. A leg can therefore
        be covered and still carry no sign, and a majority claim built over
        _covered_legs without checking n_vetoed_entries silently counts a
        zero-vote leg as agreement. The census must expose the silent legs."""
        arm = self.led["_arms"][1]
        cen = self.led["_census"]["W2"][arm]
        self.assertTrue(self.led["_coverage"]["W2"]["covered"],
                        "W2 must still be a COVERED leg — the finding is not "
                        "that the archive misses it")
        self.assertGreaterEqual(self.led["_coverage"]["W2"]["n_high_events_in_leg"],
                                5, "coverage is earned by real events")
        self.assertEqual(cen["n_vetoed_entries"], 0,
                         "W2's zero-vote shape changed — re-read the "
                         "majority claim before quoting it")
        self.assertEqual(cen["vetoed_R"], 0)
        # anti-vacuity: the SAME leg does produce evidence at a wider arm, so
        # the zero is the ±30min width's, not a dead leg
        wide = self.led["_census"]["W2"][self.led["_arms"][2]]
        self.assertGreater(wide["n_vetoed_entries"], 0)

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
