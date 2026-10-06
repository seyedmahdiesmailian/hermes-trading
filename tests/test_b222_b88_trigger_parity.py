"""b222 — the b88 ledger's funnel was priced TRIGGER-LESS on every rebuild.

scripts/b88_defcon_books.funnel_signals built the live funnel's signal
population on M15-spaced legs but never passed `m5_rows=` to
backtest_real.strategy_signal. Since b187 (Sep 2026) the live funnel opens a
pullback entry only when an M5 3-close confirmation fires alongside the zone
touch, and since b193b the aggressive lanes need the same confirmation — and
`m5_rows=None` on an M15-spaced entry stream means `m5_confirmation` sees no
rows, so `evaluate_monitor_cycle` returns wait_for_trigger for ~67% of bars and
NOTHING can ever be `market_entry_now`.

Measured on the W1 leg (2026-10-02): 5970 backtest bars, decision mix
wait_for_trigger 3986 / no_trade 1761 / wait_for_pullback 223 — zero entries.
So the b88 ledger, whose _risk_code_sha stamp blocks any risk.py edit, was
itself rebuilt against a funnel that could not fire, and the standing todo b210
("rebuild b88 before touching risk.py") was unfinishable for a reason nobody had
named: the rebuild path was broken, not merely slow.

The b81/b81-ledger scripts already discovered this exact drift for their own
ledgers (b190) and both use an `m5_stream` argument sourced from
data/backtest/b182_m5_bars.json. b88 now shares that plumbing (imported from the
one definition in scripts/b81_lane_rescore, never restated) and pins it here.

This test runs on the cached M15 leg, which the b182 M5 source covers fully,
so it is deterministic and network-free.
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestFunnelSignalsPriceTheTrigger(unittest.TestCase):
    def _cached_leg(self):
        c = json.load(open(os.path.join(ROOT, "data", "backtest",
                                        "ab_aggressive_data.json")))
        return c["M15"], c["H1"], c["H4"]

    def test_funnel_signals_passes_m5_rows_when_a_source_is_available(self):
        from scripts.b88_defcon_books import funnel_signals
        m15, h1, h4 = self._cached_leg()
        m5 = json.load(open(os.path.join(ROOT, "data", "backtest",
                                         "b182_m5_bars.json")))["bars"]
        m5 = [{"time": r[0], "high": r[1], "low": r[2], "close": r[3]}
              for r in m5]
        with_m5 = funnel_signals(m15, h1, h4, m5_stream=m5)
        # The funnel must be able to fire at all: a trigger-less funnel on this
        # leg returns {} (the regressed rebuild's signature).
        self.assertGreater(len(with_m5), 0,
                           "funnel_signals produced ZERO signals with an M5 "
                           "source present — the b187 trigger was never priced")

    def test_funnel_signals_without_a_source_matches_the_stored_population(self):
        """No m5_stream must stay byte-identical to the pre-b222 population, so
        a leg the b182 source does not cover keeps its stored number."""
        from scripts.b88_defcon_books import funnel_signals
        # b222: the CACHED leg is inside the M5 source's span, so it prices the
        # trigger and its stored number is the triggered one. The leg that must
        # stay byte-identical is one the source does NOT cover (W3).
        wins = json.load(open(os.path.join(ROOT, "data", "backtest",
                                           "b68l_independent_windows.json")))
        m15, h1, h4 = wins["W3"]["M15"], wins["W3"]["H1"], wins["W3"]["H4"]
        none_m5 = funnel_signals(m15, h1, h4)
        # RE-DERIVED 2026-10-06: W3 (1759932900-1768202100) predates the b182
        # M5 source (1775697000-1788937500), so with no m5_stream to derive
        # from the b187 trigger cannot fire and the population is 0. The stored
        # W3/_signals=1767 was itself a pre-b222 trigger-less number that
        # b222's plumbing retired; the 1767 pin was written against the very
        # drift the commit removed (b102: pin and finding move together).
        self.assertEqual(len(none_m5), 0,
                         "W3 predates the M5 source; without a stream to "
                         "derive from it must price zero signals")


if __name__ == "__main__":
    unittest.main()
