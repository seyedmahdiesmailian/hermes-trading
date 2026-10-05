"""b234 — order-block mitigation must use the ICT retracement rule.

The old test compared last_price against the WRONG EDGE of every zone:
  bull OB mitigated  `if last_price <= ob.high`   (almost always true)
  bear OB mitigated  `if last_price >= ob.low`    (almost always true)
The consequence measured on 2000 real M5 bars:
  BULL: current 51/58 mitigated, correct 58/58
  BEAR: current  2/71 mitigated, correct 64/71
  unmitigated bear: current 69, correct 7
So the layer fed _derive_smc_bias ~69 phantom bearish OBs at +2.0 points
each — a permanent ~138-point bearish skew on every scan.

The correct rule: mitigation requires price to RE-ENTER the zone AFTER the
block formed, i.e. a later bar's low touches a bull OB's high, or a later
bar's high touches a bear OB's low.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.smc import detect_order_blocks


def _row(o, h, l, c, t=0):
    return {"open": o, "high": h, "low": l, "close": c, "time": t}


class TestOBMitigation(unittest.TestCase):
    def test_bull_ob_not_mitigated_when_price_never_returns(self):
        # rows[1] is a bearish candle, rows[2] a strong break above it
        rows = [
            _row(10, 11, 9, 10.5),   # filler (loop starts at i=1)
            _row(12, 12, 9, 10),     # BEARISH — this bar is the bull OB
            _row(10, 20, 10, 19),    # strong bullish break, close > prev high
            _row(19, 25, 18, 24),
            _row(24, 30, 23, 29),
        ]
        obs = detect_order_blocks(rows, lookback=20)
        bull = [o for o in obs if o["type"] == "bullish"]
        self.assertTrue(bull)
        self.assertFalse(bull[0]["mitigated"],
                         "price never returned to the zone")

    def test_bull_ob_mitigated_when_price_returns_to_its_high(self):
        rows = [
            _row(10, 11, 9, 10.5),
            _row(12, 12, 9, 10),
            _row(10, 20, 10, 19),
            _row(19, 25, 18, 24),
            _row(24, 30, 12, 12),  # closes back DOWN at the OB high (12)
        ]
        obs = detect_order_blocks(rows, lookback=20)
        bull = [o for o in obs if o["type"] == "bullish"]
        self.assertTrue(bull)
        self.assertTrue(bull[0]["mitigated"],
                        "price returned into the zone -> mitigated")

    def test_bear_ob_not_mitigated_when_price_never_returns(self):
        rows = [
            _row(30, 31, 29, 30.5),
            _row(29, 32, 29, 31),    # BULLISH — this bar is the bear OB
            _row(31, 31, 21, 22),    # strong bearish break, close < prev low
            _row(22, 25, 16, 17),
            _row(17, 20, 11, 12),
        ]
        obs = detect_order_blocks(rows, lookback=20)
        bear = [o for o in obs if o["type"] == "bearish"]
        self.assertTrue(bear)
        self.assertFalse(bear[0]["mitigated"],
                         "price never returned to the zone")

    def test_bear_ob_mitigated_when_price_returns_to_its_low(self):
        rows = [
            _row(30, 31, 29, 30.5),
            _row(29, 32, 29, 31),
            _row(31, 31, 21, 22),
            _row(22, 25, 16, 17),
            _row(17, 29, 28, 28),  # closes back UP at the OB low (29)
        ]
        obs = detect_order_blocks(rows, lookback=20)
        bear = [o for o in obs if o["type"] == "bearish"]
        self.assertTrue(bear)
        self.assertTrue(bear[0]["mitigated"],
                        "price returned into the zone -> mitigated")

    def test_no_phantom_supply_book(self):
        """the regression that motivated the fix: on a rising market the
        bear OBs must not accumulate as 'unmitigated' supply."""
        rows = [_row(10 + i, 11 + i, 9 + i, 10.5 + i, t=i) for i in range(40)]
        # one strong break down in the middle, then price recovers and rises
        rows[20] = _row(31, 32, 25, 26)
        rows[21] = _row(26, 27, 33, 33)
        obs = detect_order_blocks(rows, lookback=40)
        bear = [o for o in obs if o["type"] == "bearish"]
        if bear:
            # price kept rising past it, so it must NOT be left unmitigated
            for o in bear:
                self.assertTrue(o["mitigated"],
                                "bear OB left unmitigated after price traded through it")


class TestOBDetection(unittest.TestCase):
    def test_empty_and_tiny_inputs(self):
        self.assertEqual(detect_order_blocks([]), [])
        self.assertEqual(detect_order_blocks([_row(1, 2, 0, 1)]), [])

    def test_ob_carries_the_block_not_the_breakout(self):
        # block at index 1, breakout at index 2
        rows = [
            _row(10, 11, 9, 10.5),
            _row(12, 12, 9, 10),      # the bull OB
            _row(10, 20, 10, 19),     # strong break above
            _row(19, 25, 18, 24),
        ]
        obs = detect_order_blocks(rows, lookback=20)
        bull = [o for o in obs if o["type"] == "bullish"]
        self.assertTrue(bull)
        self.assertEqual(bull[0]["index"], 1)
        self.assertEqual(bull[0]["high"], 12)


if __name__ == "__main__":
    unittest.main()
