"""b105 — the backtest engine must book a partial-close ladder at LIVE size.

Root cause (found 2026-09-06, trade_management-vs-journal review): the live
TP1 ladder closes the WHOLE ticket at TP1 for the balanced/weak lanes
(_partial_close_fraction -> 1.0, and auto_executor routes fraction>=1.0 to
bridge.close_position because MT5 rejects a 100% partial with retcode 10026).
The journal confirms it: every HermesPartial deal is followed by the position
disappearing, and the watchdog log shows `partial_take_profit -> ok` then a
CLOSED report seconds later — no runner survives TP1 live.

The old engines/backtest.py did not model that. On a TP1 fill it recorded the
realized partial AND then rode a phantom FULL-SIZE runner to the final TP /
BE stop / trail, adding that leg at 100% on top of the partial. Two defects,
one line:

  1. DOUBLE-COUNT — net = realized + full_runner. Repro (entry 100 / SL 98 /
     TP 104 / TP1 102, runner reaches 104): live nets 1R = 2.0; the old engine
     printed 3R = 6.0. Even the 0.5 lane was inflated: realized 1.0 + a
     FULL-size runner 4.0 = 5.0 booked where live nets 1.0 + half-size 2.0 =
     3.0.
  2. PHANTOM SLOT OCCUPANCY — a share>=1.0 trade stayed "open" for bars after
     TP1, so it blocked new entries the live system (single position, ticket
     already closed) would have taken.

The fix scales the runner leg by (1 - partial_taken) and, when the share is
>=1.0, closes the ticket at TP1 immediately (exit_reason "tp1_full") and frees
the slot — exactly what the live executor does.

Measured impact on the live funnel (cached 3000 M15, b60 ladder, run through
the EXACT live funnel via strategy_signal): exp_R 0.766 -> 0.285, net 1266 ->
463. The 0.854 merit-bar bar every b68 round compared against was inflated by
this bug; the arms were measured on the same engine, but the inflation tracks
TP1-hit-rate, so the comparison was NOT neutral — it favoured high-TP1 arms.

These tests pin the corrected economics on synthetic bars (fast, no data
fetch) so the defect can never silently return.
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines.backtest import backtest_ohlc  # noqa: E402


def _rows(tp1_idx=2, runner_high=104.5, retrace=False):
    """Flat bars, a TP1 touch at tp1_idx, then a runner bar.

    entry 100 / SL 98 (risk 2) / final TP 104 (2R) / TP1 = midpoint 102 (1R).
    """
    rows = [{"time": 1000 + i * 60, "open": 100, "high": 100.2,
             "low": 99.8, "close": 100} for i in range(6)]
    rows[tp1_idx] = {"time": 1000 + tp1_idx * 60, "open": 100, "high": 102.5,
                     "low": 100.1, "close": 102}
    if retrace:
        rows[tp1_idx + 1] = {"time": 1000 + (tp1_idx + 1) * 60, "open": 102,
                             "high": 102.2, "low": 99.9, "close": 100}
    else:
        rows[tp1_idx + 1] = {"time": 1000 + (tp1_idx + 1) * 60, "open": 102,
                             "high": runner_high, "low": 102.1, "close": 104}
    return rows


def _sig(row, fire_at=1):
    if row["time"] == 1000 + fire_at * 60:
        return {"side": "BUY", "entry": 100.0, "sl": 98.0, "tp": 104.0,
                "grade": "B", "style": "x"}
    return None


class TestFullCloseAtTP1(unittest.TestCase):
    """share >= 1.0 is a FULL close, not a partial — live closes the ticket."""

    def test_full_share_nets_exactly_one_R(self):
        # TP1 = 1R = 2.0 profit; the whole position is gone, no runner booked.
        r = backtest_ohlc(_rows(), _sig, partial_tp1_share=1.0,
                          tp1_position=0.5, spread=0.0)
        self.assertEqual(r["trades"], 1)
        self.assertAlmostEqual(r["net_pnl"], 2.0, places=6)

    def test_full_share_closes_at_tp1_not_final_tp(self):
        r = backtest_ohlc(_rows(), _sig, partial_tp1_share=1.0,
                          tp1_position=0.5, spread=0.0)
        t = r["trade_log"][0]
        self.assertEqual(t["exit_reason"], "tp1_full")
        self.assertAlmostEqual(t["exit"], 102.0, places=2)

    def test_full_share_frees_the_slot_next_bar(self):
        # A second signal on the bar AFTER TP1 must be taken: live closed the
        # ticket at TP1, so the single-position gate is empty again.
        rows = _rows(tp1_idx=2)
        def sig(row):
            if row["time"] in (1060, 1240):   # entry bar and 3 bars after TP1
                return {"side": "BUY", "entry": 100.0, "sl": 98.0,
                        "tp": 104.0, "grade": "B", "style": "x"}
            return None
        r = backtest_ohlc(rows, sig, partial_tp1_share=1.0,
                          tp1_position=0.5, spread=0.0)
        self.assertEqual(r["trades"], 2,
                         "a full TP1 close must free the slot for the next entry")

    def test_grade_fn_full_lane_matches_flat_full(self):
        # The live balanced/weak lanes reach share=1.0 through partial_share_fn;
        # the engine must treat that identically to a flat 1.0.
        from engines.trade_management import _partial_close_fraction
        r = backtest_ohlc(_rows(), _sig, partial_tp1_share=0.5,
                          partial_share_fn=_partial_close_fraction,
                          tp1_position=0.5, spread=0.0)
        self.assertAlmostEqual(r["net_pnl"], 2.0, places=6)
        self.assertEqual(r["trade_log"][0]["exit_reason"], "tp1_full")


class TestPartialRunnerScaled(unittest.TestCase):
    """share < 1.0: the surviving runner leg is (1 - share), not full size."""

    def test_half_share_runner_to_final_tp(self):
        # realized 0.5*(TP1-entry)=1.0 + half-size runner 0.5*(TP-entry)=2.0
        # = 3.0. The old engine booked the runner at FULL size: 1.0 + 4.0 = 5.0.
        r = backtest_ohlc(_rows(), _sig, partial_tp1_share=0.5,
                          tp1_position=0.5, spread=0.0)
        self.assertAlmostEqual(r["net_pnl"], 3.0, places=6)

    def test_half_share_be_stop_after_tp1(self):
        # TP1 then retrace to entry: realized 0.5R, runner exits at entry (0).
        r = backtest_ohlc(_rows(retrace=True), _sig, partial_tp1_share=0.5,
                          tp1_position=0.5, spread=0.0)
        self.assertAlmostEqual(r["net_pnl"], 1.0, places=6)

    def test_no_partial_is_unchanged(self):
        # share 0.0 = hold to final TP, full size — the fix must not touch it.
        r = backtest_ohlc(_rows(), _sig, partial_tp1_share=0.0,
                          tp1_position=0.5, spread=0.0)
        self.assertAlmostEqual(r["net_pnl"], 4.0, places=6)
        self.assertEqual(r["trade_log"][0]["exit_reason"], "tp")


class TestSpreadOnFullClose(unittest.TestCase):
    def test_full_share_spread_charged_once_on_realized(self):
        # realized = (tp1-entry)*1.0 - spread*1.0 = 2.0 - 0.2 = 1.8; ticket gone.
        r = backtest_ohlc(_rows(), _sig, partial_tp1_share=1.0,
                          tp1_position=0.5, spread=0.20)
        self.assertAlmostEqual(r["net_pnl"], 1.8, places=6)


class TestSellMirror(unittest.TestCase):
    def test_sell_full_share_nets_one_R(self):
        rows = [{"time": 1000 + i * 60, "open": 100, "high": 100.2,
                 "low": 99.8, "close": 100} for i in range(6)]
        rows[2] = {"time": 1060, "open": 100, "high": 99.9, "low": 97.5, "close": 98}
        rows[3] = {"time": 1120, "open": 98, "high": 98.1, "low": 95.5, "close": 96}
        def sig(row):
            if row["time"] == 1000:
                return {"side": "SELL", "entry": 100.0, "sl": 102.0,
                        "tp": 96.0, "grade": "B", "style": "x"}
            return None
        r = backtest_ohlc(rows, sig, partial_tp1_share=1.0,
                          tp1_position=0.5, spread=0.0)
        self.assertAlmostEqual(r["net_pnl"], 2.0, places=6)
        self.assertEqual(r["trade_log"][0]["exit_reason"], "tp1_full")


if __name__ == "__main__":
    unittest.main()
