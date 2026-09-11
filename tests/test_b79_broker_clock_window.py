"""b79 — RED-first tests for the live M5 confirmation window.

Bug: hermes_runtime built m5_confirm_rows with `_bt + 300 <= wall_utc_now`,
but the bridge stamps bar opens on the BROKER clock (~UTC+3 for CapitalXtend;
measured 10798s). Every broker stamp is ~3h AHEAD of real UTC, so the filter
rejected every row — live window permanently empty -> m5_confirmation always
False -> post-b193b no entry lane (pullback OR aggressive) can ever fire
live, while the lab (bar-relative, broker-consistent) fires normally.

Fix contract (settled_confirm_rows):
  1. A row strictly older than the freshest open has CLOSED on any broker
     clock (the bridge returns the forming bar LAST, b189) — kept without
     consulting any wall clock.
  2. The freshest row is kept only when a trustworthy broker calibration
     proves it closed (open - offset + 300 <= now_utc). No calibration ->
     dropped (conservative: never a forming close = no lookahead).
  3. Unparseable rows dropped; empty/None stream -> [].
"""
import unittest
from datetime import datetime, timezone

from hermes_runtime import settled_confirm_rows


def bar(open_ts, close):
    return {"time": open_ts, "open": close, "high": close, "low": close, "close": close}


# decision moment: 05:35:02Z — one M5 bar closed at 05:35:00, next is forming
NOW = datetime(2026, 9, 11, 5, 35, 2, tzinfo=timezone.utc)
NOW_E = int(NOW.timestamp())
OFF = 10800  # broker UTC+3


class TestB79SettledConfirmRows(unittest.TestCase):
    def test_broker_offset_stream_keeps_closed_bars(self):
        """THE regression. Bridge stream with broker stamps: bars opened
        (real) 05:10..05:30 closed, bar opened real 05:35 forming."""
        real_opens = [NOW_E - 2 - 300 + 300 * i for i in range(0, 5)]  # ..05:32? no:
        # explicit: opens real 05:10,05:15,05:20,05:25,05:30 (all closed), forming 05:35
        real_opens = [NOW_E - (NOW_E % 300) - 300 * k for k in (5, 4, 3, 2, 1)]
        rows = [bar(t + OFF, 4300.0 + i) for i, t in enumerate(real_opens)]
        rows.append(bar(NOW_E - (NOW_E % 300) + OFF, 4399.0))  # forming, freshest
        out = settled_confirm_rows(rows, now=NOW, broker_offset=None)
        self.assertEqual(len(out), 5, "all five closed bars survive; only the forming row drops")
        self.assertEqual(out[-1]["time"], rows[-2]["time"])  # last kept = real 05:30 bar
        closes = [r["close"] for r in out[-3:]]
        self.assertTrue(closes[0] < closes[1] < closes[2], "rising closes => confirmation possible")

    def test_freshest_row_kept_only_when_calibration_proves_close(self):
        """Lagged bridge: freshest stamp opened real 05:30 (closed 05:35:00
        <= 05:35:02). Uncalibrated -> dropped (can't tell forming vs closed);
        calibrated -> kept."""
        real_opens = [NOW_E - (NOW_E % 300) - 300 * k for k in (3, 2, 1)]
        rows = [bar(t + OFF, 4300.0) for t in real_opens]
        without = settled_confirm_rows(rows, now=NOW, broker_offset=None)
        with_cal = settled_confirm_rows(rows, now=NOW, broker_offset=float(OFF))
        self.assertEqual(len(without), 2)
        self.assertEqual(len(with_cal), 3)

    def test_calibration_cannot_smuggle_a_forming_close(self):
        """Freshest row opened real 05:35 (forming; closes 05:40 > now).
        Even WITH correct calibration it must be dropped — no lookahead."""
        real_opens = [NOW_E - (NOW_E % 300) - 300 * k for k in (3, 2, 1)]
        rows = [bar(t + OFF, 4300.0) for t in real_opens]
        rows.append(bar(NOW_E - (NOW_E % 300) + OFF, 4399.0))
        out = settled_confirm_rows(rows, now=NOW, broker_offset=float(OFF))
        self.assertEqual(len(out), 3)
        self.assertNotIn(4399.0, [r["close"] for r in out])

    def test_utc_stream_behaviour_matches_old_filter(self):
        """offset=0 stream: same results as the pre-b79 wall-clock filter
        (all genuinely settled rows kept, forming dropped)."""
        real_opens = [NOW_E - (NOW_E % 300) - 300 * k for k in (4, 3, 2, 1)]
        rows = [bar(t, 4300.0) for t in real_opens]
        rows.append(bar(NOW_E - (NOW_E % 300), 4301.0))  # forming
        out = settled_confirm_rows(rows, now=NOW, broker_offset=0.0)
        self.assertEqual(len(out), 4)
        legacy = [r for r in rows if r["time"] + 300 <= NOW_E]
        self.assertEqual([r["time"] for r in out], [r["time"] for r in legacy])

    def test_unparseable_rows_dropped_fail_closed(self):
        rows = [{"time": "nope"}, {}, None, bar(NOW_E - (NOW_E % 300) - 300, 4300.0),
                bar(NOW_E - (NOW_E % 300), 4301.0)]
        out = settled_confirm_rows(rows, now=NOW, broker_offset=None)
        self.assertEqual([r["close"] for r in out], [4300.0])

    def test_empty_stream(self):
        self.assertEqual(settled_confirm_rows([], now=NOW), [])
        self.assertEqual(settled_confirm_rows(None, now=NOW), [])


if __name__ == "__main__":
    unittest.main()
