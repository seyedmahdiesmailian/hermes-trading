"""b68 round 4 (PDH/PDL breakout lab) — integrity pins.

The lab arms themselves are throwaway research code, but three invariants
of scripts/b68e_pdh_lab.py are load-bearing for every FUTURE round:

1. The trading-day boundary is the data's own session break (01:00-23:45
   UTC). Grouping by broker calendar date instead would splice two sessions
   into one "day" and the level would be fiction — and the bug is silent
   because the arm still fires, just against a wrong line.
2. No lookahead: prev_day_levels() may only use bars from STRICTLY earlier
   trading days (a level containing the signal bar's own day is leakage).
3. Close confirmation: a wick through the level that closes back inside is a
   sweep, NOT a breakout (the probe that picked this candidate measured the
   difference: +0.38 ATR noise vs +1.00 ATR continuation). If the arm ever
   fires on a close-back-inside bar, the measured numbers no longer describe
   the code.

Plus the lab ledger contract: every row appended to
data/backtest/b62_strategy_lab.json carries name/trades/exp_R, so future
rounds can read "tested" without opening JSON keys by hand.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68e_pdh_lab as lab  # noqa: E402


class TestTradingDayBoundary(unittest.TestCase):
    def test_day_flips_at_session_break_not_calendar_midnight(self):
        # The data's own break is 23:45 -> 01:00 UTC, so the trading-day key is
        # the calendar date shifted back one hour: bars at 23:45 and 00:15 (the
        # break itself) still belong to the day that started at 01:00, and the
        # NEXT trading day only begins at 01:00. Grouping by broker calendar
        # date instead would splice two sessions into one "day".
        base = 1784109600                              # 2026-07-15 10:00 UTC
        a = lab.trading_day(base)
        self.assertEqual(lab.trading_day(base + 13 * 3600 + 45 * 60), a)   # 23:45 same day
        self.assertEqual(lab.trading_day(base + 14 * 3600 + 15 * 60), a)   # 00:15 -> break, same day
        self.assertNotEqual(lab.trading_day(base + 15 * 3600 + 15 * 60), a)  # 01:15 -> NEW day
        # and the two dates must be adjacent, not equal (a silent off-by-one in
        # the shift would make every day collapse onto its neighbour)
        self.assertEqual((a - lab.trading_day(base + 15 * 3600 + 15 * 60)).days, -1)

    def test_levels_use_only_strictly_earlier_days(self):
        # Every day's level must be derivable from bars BEFORE that day began.
        buckets = {}
        for r in lab.M15:
            buckets.setdefault(lab.trading_day(r["time"]), []).append(r)
        days = sorted(buckets)
        for k in range(1, len(days)):
            if days[k] not in lab.LEVELS:
                continue
            ph, pl = lab.LEVELS[days[k]]
            prev = buckets[days[k - 1]]
            self.assertEqual(ph, max(x["high"] for x in prev))
            self.assertEqual(pl, min(x["low"] for x in prev))
            # leakage guard: no bar of the level's OWN day may touch the level
            # (if it did, the level was built from the day it trades)
            for x in buckets[days[k]]:
                if x["time"] <= prev[-1]["time"]:
                    self.fail("trading-day buckets overlap — day key is broken")


class TestCloseConfirmation(unittest.TestCase):
    def _mk(self, i, sig_close, sig_high, sig_low, prior_close, ph, pl):
        """Repoint the module at a tiny synthetic series around index i."""
        rows = []
        for j in range(i + 3):
            rows.append({"time": 1000000 + 900 * j, "open": 100.0,
                         "high": 101.0, "low": 99.0, "close": 100.0})
        rows[i - 2]["close"] = prior_close
        rows[i - 1].update({"close": sig_close, "high": sig_high,
                            "low": sig_low, "open": prior_close})
        rows[i]["open"] = sig_close
        saved_m15, saved_levels, saved_idx = lab.M15, lab.LEVELS, lab.IDX
        lab.M15 = rows
        day = lab.trading_day(rows[i - 1]["time"])
        lab.LEVELS = {day: (ph, pl)}
        return saved_m15, saved_levels, saved_idx

    def _restore(self, saved):
        lab.M15, lab.LEVELS, lab.IDX = saved

    def test_wick_through_but_close_inside_does_not_fire(self):
        # sweep shape: prior close below PDH, bar pierces PDH with its HIGH
        # but CLOSES back below it -> no breakout signal
        s = self._mk(i=30, sig_close=99.5, sig_high=100.6, sig_low=99.0,
                     prior_close=99.0, ph=100.0, pl=95.0)
        try:
            self.assertIsNone(lab.pdh_break(30, 1.0))
        finally:
            self._restore(s)

    def test_close_through_fires_with_geometry(self):
        # breakout shape: closes ABOVE PDH -> BUY, SL 1.0 ATR below PDH, TP 2R
        s = self._mk(i=30, sig_close=100.6, sig_high=100.8, sig_low=99.0,
                     prior_close=99.0, ph=100.0, pl=95.0)
        try:
            sig = lab.pdh_break(30, 1.0)
            self.assertIsNotNone(sig)
            self.assertEqual(sig["side"], "BUY")
            self.assertLess(sig["sl"], 100.0)          # stop beyond the level
            self.assertAlmostEqual(sig["tp"] - sig["entry"],
                                   2 * (sig["entry"] - sig["sl"]), places=6)
        finally:
            self._restore(s)

    def test_mirror_downside(self):
        s = self._mk(i=30, sig_close=94.4, sig_high=95.5, sig_low=94.0,
                     prior_close=95.0, ph=100.0, pl=95.0)
        try:
            sig = lab.pdh_break(30, 1.0)
            self.assertIsNotNone(sig)
            self.assertEqual(sig["side"], "SELL")
            self.assertGreater(sig["sl"], 95.0)
        finally:
            self._restore(s)


class TestLabLedger(unittest.TestCase):
    def test_ledger_rows_are_complete_and_round4_recorded(self):
        p = os.path.join(ROOT, "data", "backtest", "b62_strategy_lab.json")
        with open(p) as f:
            rows = json.load(f)
        self.assertGreaterEqual(len(rows), 12)
        for r in rows:
            for key in ("name", "trades", "exp_R"):
                self.assertIn(key, r)
        names = {r["name"] for r in rows}
        self.assertIn("pdh_break_w10", names)
        self.assertIn("pdh_break_t50", names)
        w10 = [r for r in rows if r["name"] == "pdh_break_w10"][0]
        # the numbers shipped in the ledger must be the numbers the lab ran
        with open(os.path.join(ROOT, "data", "backtest",
                           "b68e_pdh_lab.json")) as f:
            labres = json.load(f)
        self.assertEqual(w10["exp_R"], labres["pdh_break_w10:ladder"]["exp_R"])
        with open(os.path.join(ROOT, "data", "backtest",
                           "b68e_pdh_confirm.json")) as f:
            conf = json.load(f)
        self.assertEqual(w10["fresh_exp_R"], conf["pdh_break_w10"]["exp_R"])
        # merit bar: fresh win alone must NEVER read as "wired"
        self.assertIn("REJECTED", w10["verdict"])


if __name__ == "__main__":
    unittest.main()
