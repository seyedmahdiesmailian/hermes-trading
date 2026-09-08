"""b141 — the day-rollover blind window, locked as an executable fact.

What this test locks (the census findings, as assertions):
  1. THE WINDOW IS REAL: a feed whose LAST day was a losing day produces a
     rollover boundary where the first cycle of the new day reads regime
     "normal" while the last cycle of yesterday read "defensive"/"locked".
     If compute_performance_state ever stops zeroing on rollover, THIS test
     goes red — that is the point (b88's pins are the same tripwire).
  2. OPTION A (carry daily_pnl/loss_streak) restores yesterday's regime on
     every blind boundary AND arms the kill switch at the same time — the
     census' central finding: option A is NOT tightening-neutral, it is a
     human gate (4h cooldown) that today's first cycle does not have.
  3. OPTION B (cold flag, kill switch NOT carried) arms nothing — its kill
     reading stays identical to the cold reading at every loss level.
  4. ARTIFACT INTEGRITY (b127/b128): the shipped ledger re-derives from its
     own embedded deal feed — same blind boundaries, same verdict.

derive() is a pure function of (deals, balance); the kill-switch probes run
under a throwaway HERMES_DATA_ROOT inside the census module, so nothing here
touches the live state files.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import b141_rollover_blind_window_census as C  # noqa: E402

BALANCE = 5000.0


def _deals(day_iso: str, profits, base_hour=20):
    """closing deals on ONE UTC day, in feed shape."""
    from datetime import datetime, timezone
    out = []
    for i, p in enumerate(profits):
        ts = datetime.fromisoformat(day_iso).replace(
            tzinfo=timezone.utc).timestamp() + base_hour * 3600 - i * 600
        out.append({"ticket": 700000 + int(ts) % 100000 + i, "time": ts,
                    "profit": p, "entry": 1, "comment": "[sl 4460.0]",
                    "symbol": "XAUUSD", "position_id": 700000 + i})
    return out


class BlindWindowIsReal(unittest.TestCase):
    def setUp(self):
        # day 1: a -1.5% losing day (crosses risk.py's 1% defensive leg,
        # NOT the 5% kill leg); day 2: one small win so the feed has 2 days.
        self.deals = (_deals("2026-09-01", [-75.0]) + _deals("2026-09-02", [5.0]))
        self.derived = C.derive(self.deals, BALANCE)

    def test_rollover_boundary_detected_as_blind(self):
        self.assertEqual(self.derived["n_boundaries"], 1)
        self.assertEqual(self.derived["blind_count"], 1,
                         "a losing yesterday must still blind the first cycle "
                         "of today — if this flips, b88's pins must be edited "
                         "in the SAME change, not after")
        row = self.derived["rows"][0]
        self.assertEqual(row["steady"]["policy"]["regime"], "defensive")
        self.assertEqual(row["cold"]["policy"]["regime"], "normal")

    def test_option_a_restores_regime_but_arms_the_kill_switch(self):
        row = self.derived["rows"][0]
        self.assertEqual(row["option_a"]["policy"]["regime"], "defensive")
        # THE finding: carrying yesterday's daily_pnl also feeds
        # check_kill_switch's daily-loss trigger. On a -1.5% day the kill
        # switch does NOT fire (threshold is 5%)...
        self.assertFalse(row["option_a"]["kill"]["halted"])
        self.assertEqual(self.derived["option_a_arms_kill_switch_that_cold_did_not"], [])

    def test_option_a_on_a_kill_threshold_day_is_a_human_gate(self):
        # -6% yesterday: steady's own kill switch WOULD have halted; the cold
        # cycle does not; option A re-arms it. That halt is the gate b141
        # must price before anyone ships option A.
        deals = _deals("2026-09-01", [-300.0]) + _deals("2026-09-02", [5.0])
        d = C.derive(deals, BALANCE)
        row = d["rows"][0]
        self.assertTrue(row["steady"]["kill"]["halted"],
                        "steady must see the halt option A would carry")
        self.assertFalse(row["cold"]["kill"]["halted"])
        self.assertTrue(row["option_a"]["kill"]["halted"])
        self.assertEqual(len(d["option_a_arms_kill_switch_that_cold_did_not"]), 1)
        self.assertIn("OPTION_A_IS_NOT_NEUTRAL",
                      C.verdict(d, {"daily_loss_pct": 0.05, "cooldown_hours": 4}))

    def test_option_b_arms_nothing(self):
        deals = _deals("2026-09-01", [-300.0]) + _deals("2026-09-02", [5.0])
        d = C.derive(deals, BALANCE)
        self.assertEqual(d["option_b_arms_kill_switch_that_cold_did_not"], [])
        row = d["rows"][0]
        self.assertFalse(row["option_b"]["kill"]["halted"])
        # and option B does NOT restore the regime either (it is a flag, not a
        # carry — the consumer code we measured ignores it entirely)
        self.assertEqual(row["option_b"]["policy"]["regime"], "normal")


class SweepThresholds(unittest.TestCase):
    """The synthetic sweep's legs must be READ from the modules, never
    restated (b109), and the blind band must start below the smallest leg."""

    def test_legs_match_the_modules(self):
        import engines.kill_switch as KS
        scan = C.synthetic_arms(BALANCE)
        self.assertEqual(scan["kill_daily_loss_leg_pct"], KS.DAILY_LOSS_LIMIT_PCT)
        self.assertIn(0.01, scan["risk_daily_loss_legs_pct"])
        self.assertIn(0.03, scan["risk_daily_loss_legs_pct"])

    def test_every_sweep_step_is_regime_blind(self):
        scan = C.synthetic_arms(BALANCE)
        self.assertEqual(len(scan["regime_blind_loss_pcts"]), scan["n_rows"],
                         "any step where cold==steady means the sweep stopped "
                         "measuring the rollover")
        self.assertEqual(scan["optA_regime_matches_steady"], scan["n_rows"])
        self.assertEqual(scan["optB_regime_matches_steady"], 0)

    def test_kill_halt_band_starts_at_the_kill_leg(self):
        scan = C.synthetic_arms(BALANCE)
        self.assertTrue(scan["optA_kill_halts"])
        self.assertGreaterEqual(min(scan["optA_kill_halts"]),
                                scan["kill_daily_loss_leg_pct"])
        self.assertEqual(scan["optB_kill_halts"], [])


class ArtifactIntegrity(unittest.TestCase):
    LEDGER = ROOT / "data" / "backtest" / "b141_rollover_blind_window_census.json"

    def test_shipped_ledger_re_derives_from_its_embedded_feed(self):
        if not self.LEDGER.exists():
            self.skipTest("ledger not built yet")
        art = json.loads(self.LEDGER.read_text(encoding="utf-8"))
        derived = C.derive(art["_deals_embedded"], float(art["_balance_used"]))
        self.assertEqual(derived["blind_count"],
                         art["derived"]["blind_count"])
        self.assertEqual(derived["blind_regime_boundaries"],
                         art["derived"]["blind_regime_boundaries"])
        self.assertEqual(derived["option_a_restores_steady_regime"],
                         art["derived"]["option_a_restores_steady_regime"])
        self.assertEqual(C.verdict(derived, art["_thresholds"]), art["verdict"])


if __name__ == "__main__":
    unittest.main()
