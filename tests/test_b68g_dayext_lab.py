"""b68 round 6 (trading-day extension lab) — integrity pins.

The lab arms are throwaway research code, but five invariants of
scripts/b68g_dayext_lab.py are load-bearing for every future round:

1. Trading-day boundary: the day open must come from the 01:00-23:45 UTC
   session (b68e's finding), not the calendar date. Grouping by calendar date
   splices the 00:xx bars of the next session into the previous day and
   invents a day open nobody on the desk would draw.
2. No lookahead: day_open_of(i) may only scan bars at index <= i, and the
   signal may only read bar i-1 (entry is bar i's OPEN). A leak inflates
   exp_R silently.
3. Hour gate: no signal before OPEN_HOUR UTC — the probe's drift is a
   late-session effect; before it the day's direction is not established.
4. THE DEAD-ARM TRAP (b69 lesson, this round caught it in its own control):
   a fade arm with a LEVEL-anchored stop puts the stop on the wrong side of
   the entry (risk <= 0) and every signal is silently dropped — trades:0
   that reads as "the fade has no edge" when nothing was measured. Pinned:
   the level-stop fade returns None on a synthetic extended-up day, and the
   shipped JSON shows the ATR-stop fade firing >100 trades.
5. Geometry honesty: the level-anchored continuation arm's stop sits several
   ATR from entry (measured mean 5.7 ATR), so its TP is absurdly far and its
   R is NOT comparable to the funnel's. Pinned so nobody reads
   dayext_cont_w10:ladder exp_R as a candidate number.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68g_dayext_lab as lab  # noqa: E402

BASE_TS = 1784109600  # a real bar time from the cached set (2026-07-15 10:00 UTC)


def _rows(specs):
    """specs: list of (open, high, low, close) or dicts; times step 900s."""
    rows = []
    for k, s in enumerate(specs):
        if isinstance(s, dict):
            r = dict(s)
        else:
            o, h, l, c = s
            r = {"open": o, "high": h, "low": l, "close": c}
        r.setdefault("time", BASE_TS + 900 * k)
        rows.append(r)
    return rows


def _flat(n, px=100.0):
    return _rows([(px, px + 0.2, px - 0.2, px)] * n)


class TestTradingDayBoundary(unittest.TestCase):
    def test_00xx_bars_belong_to_previous_trading_day(self):
        # A bar at 00:30 UTC is calendar day D but trading day D-1 (the
        # session runs 01:00-23:45). day_open_of must resolve it to the
        # 01:00 open of D-1, not to a 00:30 "open".
        import datetime
        t0 = int(datetime.datetime(2026, 7, 15, 1, 0,
                                   tzinfo=datetime.timezone.utc).timestamp())
        rows = [{"time": t0 + 900 * k, "open": 100.0, "high": 100.2,
                 "low": 99.8, "close": 100.0} for k in range(92)]  # 01:00..23:45
        for k in range(4):                                  # 00:00..00:45 next
            rows.append({"time": t0 + 82800 + 900 * k, "open": 111.0,
                         "high": 111.2, "low": 110.8, "close": 111.0})
        saved = lab.M15, lab.IDX
        lab.M15 = rows
        try:
            do, nb = lab.day_open_of(len(rows) - 1)
            self.assertAlmostEqual(do, 100.0, places=6)   # previous session's open
            self.assertGreaterEqual(nb, 93)               # counts the 00:xx bar too
        finally:
            lab.M15, lab.IDX = saved


class TestNoLookahead(unittest.TestCase):
    def test_entry_is_next_bar_open(self):
        # Build a flat day then a violent rally that closes 3 ATR above the
        # day open at hour >= OPEN_HOUR; the signal's entry must be the NEXT
        # bar's open, and the direction must be BUY (continuation).
        import datetime
        rows = _flat(60)
        # move the last bars to 13:00+ UTC by fixing times: pick a day whose
        # 13:00 exists in the synthetic window
        t0 = rows[0]["time"]
        # shift so bar 58 lands at hour 13
        bar58_hour = datetime.datetime.fromtimestamp(t0 + 900 * 58,
                                                     datetime.timezone.utc).hour
        shift = ((13 - bar58_hour) % 24) * 3600
        rows = [dict(r, time=r["time"] + shift) for r in rows]
        rows[57] = dict(rows[57], close=100.0)
        rows[58] = dict(rows[58], open=100.0, high=106.0, low=99.9, close=105.5)
        rows[59] = dict(rows[59], open=105.4, high=106.0, low=105.0, close=105.6)
        saved = lab.M15, lab.IDX
        lab.M15 = rows
        try:
            sig = lab.dayext(59, "cont", "atr")
            self.assertIsNotNone(sig, "extended-up day at hour 13 must fire")
            self.assertEqual(sig["side"], "BUY")
            self.assertAlmostEqual(sig["entry"], 105.4, places=6)  # bar 59 open
            self.assertLess(sig["sl"], sig["entry"])
            self.assertGreater(sig["tp"], sig["entry"])
        finally:
            lab.M15, lab.IDX = saved

    def test_hour_gate_blocks_early_day(self):
        # Same extension but the signal bar sits at hour 5 (< OPEN_HOUR=13):
        # the arm must stay silent — the probe's drift is a late-session effect.
        import datetime
        rows = _flat(60)
        t0 = rows[0]["time"]
        bar58_hour = datetime.datetime.fromtimestamp(t0 + 900 * 58,
                                                     datetime.timezone.utc).hour
        shift = ((5 - bar58_hour) % 24) * 3600
        rows = [dict(r, time=r["time"] + shift) for r in rows]
        rows[58] = dict(rows[58], open=100.0, high=106.0, low=99.9, close=105.5)
        rows[59] = dict(rows[59], open=105.4, high=106.0, low=105.0, close=105.6)
        saved = lab.M15, lab.IDX
        lab.M15 = rows
        try:
            self.assertIsNone(lab.dayext(59, "cont", "atr"))
        finally:
            lab.M15, lab.IDX = saved


class TestDeadArmTrap(unittest.TestCase):
    def _extended_up_rows(self):
        import datetime
        rows = _flat(60)
        t0 = rows[0]["time"]
        bar58_hour = datetime.datetime.fromtimestamp(t0 + 900 * 58,
                                                     datetime.timezone.utc).hour
        shift = ((13 - bar58_hour) % 24) * 3600
        rows = [dict(r, time=r["time"] + shift) for r in rows]
        rows[58] = dict(rows[58], open=100.0, high=106.0, low=99.9, close=105.5)
        rows[59] = dict(rows[59], open=105.4, high=106.0, low=105.0, close=105.6)
        return rows

    def test_level_stop_fade_is_geometrically_dead(self):
        # THE b69 TRAP: fading an up-extension with a stop anchored at
        # day_open + 1 ATR puts the SELL's stop BELOW its entry -> risk <= 0
        # -> every signal dropped -> trades:0 that reads as "fade has no
        # edge". If anyone ever "fixes" the fade arm back to stop='level',
        # this test documents why that is a dead arm, not a result.
        saved = lab.M15, lab.IDX
        lab.M15 = self._extended_up_rows()
        try:
            self.assertIsNone(lab.dayext(59, "fade", "level", ext=2.5))
            sig = lab.dayext(59, "fade", "atr", ext=2.5)   # the healed geometry
            self.assertIsNotNone(sig)
            self.assertEqual(sig["side"], "SELL")
        finally:
            lab.M15, lab.IDX = saved


class TestLedger(unittest.TestCase):
    def test_lab_results_are_recorded_and_alive(self):
        p = os.path.join(ROOT, "data", "backtest", "b68g_dayext_lab.json")
        with open(p) as f:
            res = json.load(f)
        probe = res["_shape_probe"]
        # the trigger must actually fire (b69 anti-vacuity): >100 eligible bars
        self.assertGreater(probe["fire_at_1.5atr"], 100)
        for arm in ("dayext_cont_w10", "dayext_cont_a10",
                    "dayext_cont_w10_e25", "dayext_cont_a10_e25",
                    "dayext_fade_a10"):
            row = res[f"{arm}:ladder"]
            self.assertGreater(row["trades"], 0, f"{arm} fired 0 — dead arm")
            self.assertIn("exp_R", row)
        # the fade control must have a real sample (it is the loop's MEAN-REV
        # data point for the day-shape family; 0 trades would be a lie)
        self.assertGreater(res["dayext_fade_a10:ladder"]["trades"], 100)

    def test_level_stop_geometry_is_not_funnel_comparable(self):
        # dayext_cont_w10's stop is anchored at the day open, measured mean
        # 5.7 ATR from entry (max 11.2) — its TP is 11+ ATR away and its R is
        # a different unit than the funnel's ~1 ATR risk. Pin the fact so the
        # 1.096 headline can never be quoted as a candidate number.
        p = os.path.join(ROOT, "data", "backtest", "b68g_dayext_lab.json")
        with open(p) as f:
            res = json.load(f)
        self.assertGreater(res["dayext_cont_w10:ladder"]["trades"], 0)
        self.assertLess(res["dayext_cont_a10:ladder"]["exp_R"],
                        res["dayext_cont_w10:ladder"]["exp_R"])


if __name__ == "__main__":
    unittest.main()
