"""b72 — abbreviated-price expansion was reading RADIN signals ~230$ off.

Root cause: 3-digit values ('403' meaning 4403) were added onto a hundreds
base (4400 + 403 = 4803 / 4703), so every RADIN signal with trailing-3
abbreviations produced garbage entry/SL/TP, and the RR gate then rejected
a signal it had never actually read correctly.

These tests pin the real RADIN texts from 2026-09-04 against the prices the
channel actually meant, verified against the broker's own M5 path.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.signal_parser import expand_abbreviated_price, parse_signal

# (low, high) traded over the 24h before the 2026-09-04 signals, from the
# broker's H1 candles — used to disambiguate two-letter abbreviations.
BAND = (4365.48, 4510.89)


class TestThreeDigitAbbreviation(unittest.TestCase):
    def test_trailing_three_is_not_added_to_hundreds_base(self):
        # '403' at a 4471 market means 4403, not 4703/4803
        self.assertEqual(expand_abbreviated_price(403, 4471.0), 4403.0)
        self.assertEqual(expand_abbreviated_price(393, 4471.0), 4393.0)
        self.assertEqual(expand_abbreviated_price(383, 4471.0), 4383.0)

    def test_three_digit_near_rollover_stays_sane(self):
        # anchor 4405: 4303 is 102 away, 4403 is 2 away
        self.assertEqual(expand_abbreviated_price(403, 4405.0), 4403.0)
        self.assertEqual(expand_abbreviated_price(103, 4405.0), 4103.0)


class TestAnchorGeometry(unittest.TestCase):
    def test_sl_and_tp_anchor_to_entry_not_market(self):
        # Entry 4467, SL '47' — 4447 is 20 from the ENTRY but 31 from a 4478
        # market. Anchoring to the market was producing wrong stops.
        s = parse_signal(
            "[💬 از RADIN VIP NEW ⚡]\n67 و 57 خرید\nاستاپ 47\n"
            "تی پی 77 ، 87 ، 97 ، 507 ، 17",
            current_price=4478.5, price_band=BAND)
        self.assertEqual(s.side, "BUY")
        self.assertEqual(s.entry, 4467.0)
        self.assertEqual(s.entries, [4467.0, 4457.0])
        self.assertEqual(s.sl, 4447.0)
        self.assertEqual(s.tp, 4477.0)
        self.assertEqual(round(s.computed_rr, 2), 0.5)

    def test_sell_ladder_parses_below_market(self):
        s = parse_signal(
            "[💬 از RADIN VIP NEW ⚡]\n390 و 400 فروش\nاستاپ 410\n"
            "تی پی 380 ، 70 ، 60",
            current_price=4469.1, price_band=BAND)
        self.assertEqual(s.side, "SELL")
        self.assertEqual(s.entry, 4390.0)
        self.assertEqual(s.entries, [4390.0, 4400.0])
        self.assertEqual(s.sl, 4410.0)      # SL above entry for a SELL
        self.assertEqual(s.tp, 4380.0)      # TP below entry for a SELL

    def test_two_digit_entry_uses_traded_band_when_ambiguous(self):
        # '24' at a 4474 market: 4424 (102$ below) vs 4524 (50$ above).
        # 4524 sits above the day's real high (4510.89) → it is the misread.
        s = parse_signal(
            "[💬 از RADIN VIP NEW ⚡]\n24 و 14 خرید\nاستاپ 4\n"
            "تی پی 34 ، 44 ، 54 ، 64 ، 74",
            current_price=4474.9, price_band=BAND)
        self.assertEqual(s.entry, 4424.0)
        self.assertEqual(s.entries, [4424.0, 4414.0])
        self.assertEqual(s.sl, 4404.0)

    def test_no_band_still_parses(self):
        # Bridge down / no history must never drop a signal — fall back to
        # nearest-candidate geometry.
        s = parse_signal("XAUUSD BUY 4467 SL 4447 TP 4477", 4470.0)
        self.assertEqual(s.entry, 4467.0)
        self.assertEqual(s.sl, 4447.0)


class TestFullPriceUnaffected(unittest.TestCase):
    def test_four_digit_prices_pass_through(self):
        s = parse_signal("XAUUSD BUY 4386\nMORE BUY 4380\nSL 4370\nTP1 4389",
                         4471.2, price_band=BAND)
        self.assertEqual(s.entry, 4386.0)
        self.assertEqual(s.entries, [4386.0, 4380.0])
        self.assertEqual(s.sl, 4370.0)
        self.assertEqual(s.tp, 4389.0)


if __name__ == "__main__":
    unittest.main()
