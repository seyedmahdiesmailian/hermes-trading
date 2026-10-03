"""b93 — MEASURE THE MEDIUM BEFORE THE GATE: market-hours pass.

Pins the facts this round shipped, in the order the rule demands (medium
first, gate second):

  1. THE MEDIUM IS FRAME-SHIFTED, NOT EMPTY. Every cached/confirm leg has 0
     Sunday bars read naively and >0 after de-rotating by the broker server
     offset — so b92's "0 Sunday bars" was never a coverage statement, it was
     a frame artifact. The daily-halt signature proves the direction: the
     naive frame is missing hour 00 (impossible for a UTC gold feed, whose
     halt sits at 21:00 UTC), the true frame is missing hour 21.
  2. THE BOOK VERDICT IS INVERTED, not zero: in the naive frame
     is_market_open blocks ONLY bars that were actually open (mis_kills > 0,
     true-frame kills missed = same count) — a "0 kills" or "N kills" book
     number here is meaningless, so book_can_price_this_gate stays false.
  3. THE LIVE RECORD is the honest medium: plan_history cycles are wall-clock
     UTC, market_hours blocked 555/1552 in the shipped record, and every
     blocked cycle is Fri/Sat/Sun — the gate's real population.
  4. THE SHADOW ROW: cooldown's post-open window is a strict subset of
     market_hours' OPEN period (both_gates_block == 0 over a minute grid), so
     the two time gates are DISJOINT and neither can be removed as "already
     covered" — b92's finding reproduced from the other side.
  5. THE BOUNDARY MISMATCH was the gate's key output, and 2026-10-02 it was
     APPLIED by direction: the literals moved from Sun 23:00 / Fri 22:00 to
     the broker-measured Sun 22:00 / Fri 21:00 UTC. The ledger still records
     the escalation wording as the evidence trail; this test now pins the
     gate to the NEW boundary (test_gate_literals_match_the_measured_boundary).

Plus the standard lab hygiene: shipped JSON with the verdict block, constants
imported from the live modules (never restated), and no live-path module
imports the lab script.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "data" / "backtest" / "b93_market_hours_gate.json"
SCRIPT = REPO / "scripts" / "b93_market_hours_gate.py"

import sys
sys.path.insert(0, str(REPO))

from engines import cooldown as cd                     # noqa: E402  (live module)
from engines.market_hours import is_market_open        # noqa: E402  (live gate)
from engines import storage                            # noqa: E402  (history collector)

LEGS = ("cached", "W1", "W2", "W3", "W4")


def _led():
    with open(LEDGER, encoding="utf-8") as f:
        return json.load(f)


class TestShippedLedger(unittest.TestCase):
    def test_ledger_exists_with_verdict(self):
        self.assertTrue(LEDGER.exists(),
                        "b93 ledger missing — run scripts/b93_market_hours_gate.py")
        v = _led()["_verdict"]
        for k in ("medium_is_utc", "blocked_bars_naive_frame_total",
                  "blocked_bars_true_frame_total", "book_can_price_this_gate",
                  "live_fire_rate", "shadow_verdict", "adaptive_reachable",
                  "boundary_mismatch", "action"):
            self.assertIn(k, v)

    def test_five_legs_reported_in_both_frames(self):
        led = _led()
        for leg in LEGS:
            self.assertIn("frame", led[leg])
            self.assertIn("naive_frame", led[leg]["frame"])
            self.assertIn("true_frame", led[leg]["frame"])
            self.assertIn("population", led[leg])


class TestMediumIsFrameShifted(unittest.TestCase):
    """The b93 rule's own subject: the medium, audited before the gate."""

    def test_naive_frame_has_no_sunday_true_frame_does(self):
        led = _led()
        for leg in LEGS:
            fr = led[leg]["frame"]
            self.assertEqual(fr["naive_frame"]["sunday_bars"], 0,
                             f"{leg}: naive frame should show 0 Sunday bars")
            self.assertGreater(fr["true_frame"]["sunday_bars"], 0,
                               f"{leg}: de-rotated frame MUST show Sunday "
                               "bars — the medium is frame-shifted, not empty")

    def test_daily_halt_signature_points_the_right_way(self):
        """Server-time gold feeds halt at server midnight; in true UTC the
        halt must land at 21:00 (the naive frame's missing hour 00 is the
        tell that the stamps are server time)."""
        led = _led()
        for leg in LEGS:
            fr = led[leg]["frame"]
            self.assertIn(0, fr["naive_frame"]["zero_hours"],
                          f"{leg}: naive frame should be missing hour 00")
            self.assertEqual(fr["true_frame"]["zero_hours"], [21],
                             f"{leg}: true frame's daily halt must read 21:00 UTC")

    def test_weekly_gap_reads_sunday_open_only_in_true_frame(self):
        led = _led()
        for leg in LEGS:
            fr = led[leg]["frame"]
            self.assertNotEqual(fr["naive_frame"]["weekly_gap"].get("first_after_dow"),
                                "Sun", "naive frame must NOT read a Sunday reopen")
            self.assertEqual(fr["true_frame"]["weekly_gap"]["first_after_dow"], "Sun",
                             f"{leg}: true frame's weekly gap must end on Sunday")

    def test_offset_used_is_the_published_calibration(self):
        """The ledger must de-rotate with the watchdog's published offset
        (same source b35 uses), not a restated literal."""
        from engines.broker_clock import load_offset
        led = _led()
        off = led["cached"]["frame"]["offset_sec_used"]
        self.assertGreater(off, 3500, "offset must be a real server calibration")
        self.assertLess(off, 43200)
        live = load_offset(now=dt.datetime.now(dt.timezone.utc))
        if live:  # watchdog healthy: ledger offset within 60 s of it
            self.assertLess(abs(off - live), 60.0)


class TestBookVerdictIsInverted(unittest.TestCase):
    def test_naive_kills_are_all_actually_open_bars(self):
        led = _led()
        for leg in LEGS:
            p = led[leg]["population"]
            self.assertGreater(p["naive_kills_that_were_actually_open"], 0,
                               f"{leg}: naive frame must be killing open-market bars")
            self.assertEqual(p["blocked_bars_naive_frame"],
                             p["naive_kills_that_were_actually_open"],
                             f"{leg}: every naive-frame kill is a mis-kill")
            self.assertFalse(p["frames_agree"])

    def test_book_cannot_price_the_gate(self):
        v = _led()["_verdict"]
        self.assertFalse(v["medium_is_utc"])
        self.assertFalse(v["book_can_price_this_gate"])


class TestLiveRecord(unittest.TestCase):
    def test_blocked_cycles_are_only_fri_sat_sun(self):
        lr = _led()["live_record"]
        self.assertGreater(lr["cycles_blocked_by_market_hours"], 0)
        self.assertEqual(sorted(lr["blocked_by_weekday"]), ["Fri", "Sat", "Sun"])
        self.assertEqual(sum(lr["blocked_by_weekday"].values()),
                         lr["cycles_blocked_by_market_hours"])

    def test_live_record_matches_wall_clock_gate(self):
        """Recompute the fire rate from plan_history directly — the ledger
        number must not drift from the live gate's own answer. Two pins make
        this deterministic (b94's bug class): the window is bounded by the
        ledger's own last stamp (cron appends a new cycle every 15 min), and
        cycles are counted as DISTINCT created_at values, because a finalised
        plan is rewritten under a new write-time filename with the same stamp
        (observed: 20260906_060002_xau-f2e037be / 20260906_061502_xau-f2e037be).

        b104 (2026-09-06): the EXACT count equality held only while the whole
        window still existed on disk. engines/storage.py prunes plan_history at
        PLAN_HISTORY_KEEP=1500 files (amortized, ~10% over), so the ledger's
        OLDEST stamps are deleted under it — measured: the shipped 771-cycle
        record was recomputable at 695, a permanent RED on a healthy repo, the
        same location-dependence class as b91/b94 (the test compared a snapshot
        to a directory another process owns). The claim is now split honestly:
        the RATE (the number that means anything) is compared with a
        tolerance, the COUNT is compared exactly ONLY while the window is
        intact, and a stale window must be a LOUD freshness failure, never a
        silent count mismatch."""
        # WP1: plan_history is live state, no longer tracked in git. The
        # freshness tripwire below is only meaningful on a box that HAS a
        # live window — a bare checkout skips instead of certifying nothing.
        _hist = REPO / "data/xau_plan/plan_history"
        if not _hist.is_dir() or not any(_hist.glob("*.json")):
            self.skipTest("no live plan_history on this checkout")
        lr = _led()["live_record"]
        cutoff = dt.datetime.fromisoformat(lr["last"])
        first = dt.datetime.fromisoformat(lr["first"])
        # Same collector the ledger used: disk + the pruned prefix recovered
        # from git. Reading the directory alone would re-introduce the b104
        # location-dependence (a pruned window cannot match a full one).
        stamps = {s for s in storage.collect_plan_history_stamps(REPO / "data" / "xau_plan")
                  if dt.datetime.fromisoformat(s) <= cutoff}
        self.assertTrue(stamps, "no plan_history survives at all — the "
                                "recomputation is vacuous, not passing")
        blocked = sum(1 for s in stamps
                      if not is_market_open(dt.datetime.fromisoformat(s)))
        window_intact = min(dt.datetime.fromisoformat(s) for s in stamps) <= first
        if window_intact:
            # nothing pruned: the strong claim still applies
            self.assertEqual(lr["cycles"], len(stamps))
            self.assertEqual(lr["cycles_blocked_by_market_hours"], blocked)
        else:
            # pruned prefix: counts cannot match by construction, so compare
            # the RATE and prove the pruning is real (else this branch is a
            # quiet way to dodge the exact assertion)
            self.assertLess(len(stamps), lr["cycles"],
                            "window reported as pruned but nothing is missing")
            # b222: the pruned branch is only valid when the surviving window
            # is long enough to contain a full market cycle. data/xau_plan is
            # gitignored, so the git-prefix recovery b104 relied on returns
            # NOTHING (never tracked => --diff-filter=D finds no file), and the
            # surviving slice shrinks monotonically under storage's keep-cap.
            # A 3-day tail of an open-market week has a structurally different
            # RATE from the 35-day ledger (0.113 vs 0.204 measured): the
            # comparison does not mean the gate drifted, it means the window
            # is gone. Compare RATE only over a window that can hold a weekend.
            span_days = (max(dt.datetime.fromisoformat(s) for s in stamps)
                         - min(dt.datetime.fromisoformat(s) for s in stamps)
                         ).total_seconds() / 86400
            if span_days < 7.0:
                self.skipTest(
                    f"surviving plan_history is only {span_days:.1f} days "
                    f"({len(stamps)} cycles) — too short to compare a wall-clock "
                    "RATE against a multi-week ledger, and the git recovery "
                    "b104 relied on is inert on a gitignored dir. Re-run "
                    "scripts/b93_market_hours_gate.py to re-stamp the ledger "
                    "against the window that still exists")
            shipped = lr["share_of_cycles_blocked"]
            now = blocked / len(stamps)
            self.assertLess(abs(now - shipped), 0.06,
                            f"live fire RATE drifted: ledger {shipped:.3f} vs "
                            f"recomputed {now:.3f} over {len(stamps)} cycles")
        age_days = (dt.datetime.now(dt.timezone.utc) - cutoff).total_seconds() / 86400
        self.assertLess(age_days, 3.0,
                        f"live_record is {age_days:.1f} days stale — re-run "
                        "scripts/b93_market_hours_gate.py; a stale snapshot "
                        "makes this test certify a window nobody can re-measure")


class TestShadowRow(unittest.TestCase):
    def test_gates_are_disjoint_minute_grid(self):
        sh = _led()["shadow"]
        grid = sh["minute_grid_week"]
        self.assertEqual(grid["both_gates_block"], 0,
                         "cooldown window must sit inside market_hours OPEN")
        self.assertEqual(grid["only_cooldown"], cd.POST_OPEN_COOLDOWN_MIN)
        self.assertTrue(sh["verdict"].startswith("DISJOINT"))

    def test_post_open_window_is_open_market(self):
        """The exact minutes cooldown protects must be market-open, or the
        shadow conversation re-opens (same pin as b92, from this side)."""
        for row in _led()["shadow"]["probe_post_open_window"]:
            t = dt.datetime.fromisoformat(row["at"])
            self.assertTrue(is_market_open(t), f"{row['at']} must be OPEN")


class TestBoundaryMismatchRecordedNotApplied(unittest.TestCase):
    def test_ledger_carries_the_escalation(self):
        b = _led()["boundary_vs_reality"]
        self.assertEqual(b["inferred_weekly_open_utc"], "Sun 22:00")
        self.assertEqual(b["inferred_weekly_close_utc"], "Fri 21:00")
        v = _led()["_verdict"]
        self.assertIn("ESCALATE", v["action"])
        self.assertIn("Fri 21:00", v["boundary_mismatch"])

    def test_gate_literals_match_the_measured_boundary(self):
        """2026-10-02 direction: the b93 escalation was applied — the gate
        now mirrors the broker stream (Sun 22:00 / Fri 21:00 UTC) instead of
        the old conservative/permissive literals. Asserts the move landed on
        BOTH edges and that the intermediate hour flipped correctly."""
        # Sunday edge: 21:30 closed, 22:00 open
        self.assertFalse(is_market_open(dt.datetime(2026, 9, 6, 21, 30,
                                                   tzinfo=dt.timezone.utc)))
        self.assertTrue(is_market_open(dt.datetime(2026, 9, 6, 22, 30,
                                                   tzinfo=dt.timezone.utc)))
        # Friday edge: 20:45 open (last real bar), 21:00 closed
        self.assertTrue(is_market_open(dt.datetime(2026, 9, 4, 20, 45,
                                                    tzinfo=dt.timezone.utc)))
        self.assertFalse(is_market_open(dt.datetime(2026, 9, 4, 21, 30,
                                                    tzinfo=dt.timezone.utc)))
        # The hour the old gate got wrong on both ends
        self.assertTrue(is_market_open(dt.datetime(2026, 9, 6, 22, 15,
                                                   tzinfo=dt.timezone.utc)))
        self.assertFalse(is_market_open(dt.datetime(2026, 9, 4, 21, 15,
                                                    tzinfo=dt.timezone.utc)))


class TestHygiene(unittest.TestCase):
    def test_no_live_module_imports_the_lab_script(self):
        hits = subprocess.run(
            ["grep", "-rl", "--include=*.py", "b93_market_hours_gate", "engines/",
             "hermes_master.py", "hermes_runtime.py", "position_daemon.py",
             "signal_daemon.py"],
            cwd=REPO, capture_output=True, text=True).stdout.strip()
        # market_hours.py cites the ledger as its evidence trail, which is a
        # prose reference, not an import — a citation is how every other gate
        # documents its provenance, and the guard must not be forced to delete
        # the pointer to the measurement that justifies its own boundary.
        hits = "\n".join(f for f in hits.splitlines() if f != "engines/market_hours.py")
        self.assertEqual(hits, "", f"live path imports the lab script: {hits}")

    def test_reachability_constants_match_live_modules(self):
        r = _led()["reachability"]
        self.assertFalse(r["learning_can_move_market_hours"])
        self.assertEqual(r["boundaries"]["sunday_open_utc"], "22:00")
        self.assertEqual(r["boundaries"]["friday_close_utc"], "21:00")


if __name__ == "__main__":
    unittest.main()
