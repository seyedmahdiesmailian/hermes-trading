"""b131 — the news-veto dial in engines/backtest.py: parity + clock fields.

Pins the three properties the b131 ledger depends on:
 1. news_veto_windows=[] is BYTE-IDENTICAL to passing nothing (additive dial,
    the b129/b130 convention — an empty dial must be a no-op).
 2. The veto fires on ENTRY TIME, before the signal is even consulted: a trade
    whose entry bar sits in a window disappears, and one outside it survives.
 3. trade_log carries entry_time/exit_time (the reusable clock census that
    makes future time-gate questions ledger arithmetic, b131 step 2).
"""
import unittest

from engines.backtest import backtest_ohlc


def rows(times_prices):
    return [{"time": t, "open": p, "high": p + 2, "low": p - 2, "close": p}
            for t, p in times_prices]


T0 = 1_700_000_000
STEP = 900


def flat_rows(n=40):
    """Alternating closes so every entry gets stopped out on the next bar —
    the fixture needs CLOSED trades to appear in trade_log at all."""
    return rows([(T0 + i * STEP, 2000.0 if i % 2 == 0 else 1985.0)
                 for i in range(n)])


def always_long(row):
    return {"side": "BUY", "entry": row["close"], "sl": row["close"] - 10.0,
            "tp": row["close"] + 25.0,
            "style": "trend", "grade": "A"}


class B131NewsVetoDial(unittest.TestCase):
    def _run(self, **kw):
        return backtest_ohlc(flat_rows(), always_long, min_rr=1.0,
                             spread=0.0, **kw)

    def test_empty_windows_is_byte_identical_to_no_dial(self):
        base = self._run()
        empty = self._run(news_veto_windows=[])
        self.assertEqual(base, empty)   # whole result dict, stats + trade_log

    def test_veto_removes_exactly_the_entries_inside_windows(self):
        base = self._run()
        entries = [int(t["entry_time"]) for t in base["trade_log"]]
        self.assertTrue(entries, "fixture must produce trades")
        victim = entries[0]   # the first entry: vetoing a LATER entry can
        # legitimately OPEN new ones (the blocked bar frees the position slot
        # for the next bar, exactly like live), so only the first is a clean
        # subtraction in this fixture.
        vetoed = self._run(news_veto_windows=[(victim, victim)])
        after = [int(t["entry_time"]) for t in vetoed["trade_log"]]
        self.assertNotIn(victim, after)
        self.assertEqual([e for e in entries if e != victim], after)

    def test_veto_applied_after_signal_like_live_check7(self):
        """Order parity with live: the producer runs first, THEN
        auto_executor Check 7 refuses the proposal on a blackout bar. So the
        blocked bar IS consulted by signal_fn but never becomes a trade, and
        the slot stays free for the next bar."""
        calls = []

        def spy(row):
            calls.append(int(row["time"]))
            return always_long(row)

        base = backtest_ohlc(flat_rows(), spy, min_rr=1.0, spread=0.0)
        calls.clear()
        victim = int(base["trade_log"][0]["entry_time"])
        vetoed = backtest_ohlc(flat_rows(), spy, min_rr=1.0, spread=0.0,
                               news_veto_windows=[(victim, victim)])
        self.assertIn(victim, calls, "live consults the producer, then Check 7 vetoes")
        self.assertNotIn(victim, [int(t["entry_time"]) for t in vetoed["trade_log"]])
        self.assertEqual(len(vetoed["trade_log"]), len(base["trade_log"]) - 1)

    def test_clock_fields_present(self):
        for t in self._run()["trade_log"]:
            self.assertIsInstance(t["entry_time"], int)
            self.assertIsInstance(t["exit_time"], int)
            self.assertGreaterEqual(t["exit_time"], t["entry_time"])


if __name__ == "__main__":
    unittest.main()
