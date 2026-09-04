"""b74 regression: line-per-line TP ladders must not be lost.

Channels like goldfree / gtmofx / goldsystem write one target per line
("TP1 4389\\nTP2 4392\\n...") instead of a comma run. The generic TP pattern
used to capture the rung INDEX as the price ("TP" + "1"), so the ladder
vanished and every such signal was scored on TP1 alone — which made good
signals look like RR 0.19 and the gate rejected them.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.signal_parser import parse_signal  # noqa: E402

# Verbatim shape from data/radin/history_goldfree.jsonl
GOLDFREE = ("XAUUSD BUY 4386\nMORE BUY\xa0 4380\n\nTP¹ 4389\nTP² 4392\n"
            "TP³ 4395\nTP⁴ 4398\nTP⁵ 4400\nTP⁶ 4403\nTP⁷ 4416\n\n\n"
            "TP OPEN \n\n\nTP OPEN\n\nSL 4370 SCALPING")

GTMO = ("🥇  #XAUUSD | SELL 4438.00\n\n📊 Target 1 : 4433.00 | "
        "Target 2 : 4428.00 | Target 3 : 4420.00\n\n\n⚠️ Stoploss : 4444.00 🚨")


class TestB74LinePerLineLadder(unittest.TestCase):

    def test_goldfree_superscript_ladder_is_recovered(self):
        sig = parse_signal(GOLDFREE, current_price=4316.0,
                           price_band=(4200.0, 4436.0))
        self.assertEqual(sig.side, 'BUY')
        self.assertEqual(sig.entry, 4386.0)
        self.assertEqual(sig.sl, 4370.0)
        self.assertEqual(sig.tp, 4389.0)
        self.assertEqual(len(sig.tps), 7, f'ladder lost: {sig.tps}')
        self.assertEqual(sig.tps[0], 4389.0)
        self.assertEqual(sig.tps[-1], 4416.0)

    def test_rung_index_is_never_read_as_a_price(self):
        """The old bug: 'TP1 4389' captured 1 as the target price."""
        sig = parse_signal(GOLDFREE, current_price=4316.0,
                           price_band=(4200.0, 4436.0))
        for t in [sig.tp, sig.tp2] + list(sig.tps):
            self.assertGreater(t, 100.0, f'rung index leaked as price: {t}')

    def test_ladder_reward_beats_tp1_reward(self):
        sig = parse_signal(GOLDFREE, current_price=4316.0,
                           price_band=(4200.0, 4436.0))
        risk = sig.entry - sig.sl
        self.assertGreater(sig.tps[-1] - sig.entry, sig.tp - sig.entry)
        self.assertGreater(risk, 0)

    def test_pipe_separated_targets_gtmo(self):
        sig = parse_signal(GTMO, current_price=4438.0,
                           price_band=(4380.0, 4470.0))
        self.assertEqual(sig.side, 'SELL')
        self.assertEqual(sig.entry, 4438.0)
        self.assertEqual(sig.sl, 4444.0)
        self.assertEqual(sig.tp, 4433.0)
        self.assertGreaterEqual(len(sig.tps), 3, f'ladder lost: {sig.tps}')
        self.assertEqual(sig.tps[-1], 4420.0)

    def test_single_tp_stays_single(self):
        sig = parse_signal('SELL 4400 SL 4410 TP 4380', current_price=4400.0,
                           price_band=(4360.0, 4440.0))
        self.assertEqual(sig.tp, 4380.0)
        self.assertEqual(sig.sl, 4410.0)
        self.assertLessEqual(len(sig.tps or []), 1)

    def test_persian_tp_keyword_still_works(self):
        sig = parse_signal('تی پی 4380', current_price=4400.0,
                           price_band=(4360.0, 4440.0))
        self.assertEqual(sig.tp, 4380.0)

    def test_typo_rung_is_dropped(self):
        """b74b: goldfree posted 'TP7 39980' for a 4024 market (meant 3998).

        Left in, that one digit made the signal read as RR 286 and swung the
        90-day replay by -17,000$.
        """
        typo = ('XAUUSD SELL 4024\nMORE SELL\xa0 4030\n\nTP¹ 4020\nTP² 4018\n'
                'TP³ 4014\nTP⁴ 4010\nTP⁵ 4006\nTP⁶ 4002\nTP⁷ 39980\n\n'
                'SL 4042 SCALPING')
        sig = parse_signal(typo, current_price=4030.0,
                           price_band=(3950.0, 4100.0))
        self.assertEqual(sig.side, 'SELL')
        self.assertNotIn(39980.0, sig.tps, f'typo rung survived: {sig.tps}')
        self.assertEqual(sig.tps, [4020.0, 4018.0, 4014.0, 4010.0,
                                   4006.0, 4002.0])
        # reward must stay a sane multiple of risk
        risk = sig.sl - sig.entry
        self.assertLess((sig.tps[0] and (sig.entry - sig.tps[-1])) / risk, 10)


    def test_red_emoji_on_stop_line_does_not_flip_side(self):
        """b74e: goldsystem decorates the STOP line of a BUY with 🔴.

        '🔵Buy 4404/4407 / 🔴Stop 4398' used to parse as SELL because the red
        circle was checked before the word 'Buy' — producing a stop above the
        entry and 32% untradeable legs from that channel.
        """
        msg = ('🔵Buy\xa0 4404/4407\n\n🔴Stop 4398\n\nTp1:4412\nTp2:4418\n'
               'Tp3:4425\nTp4:4435\nTp5:4445\n\n🗓Expiration Time: 2026-09-01')
        sig = parse_signal(msg, current_price=4404.0,
                           price_band=(4300.0, 4500.0))
        self.assertEqual(sig.side, 'BUY')
        self.assertEqual(sig.entry, 4404.0)
        self.assertLess(sig.sl, sig.entry, 'stop must sit below a BUY entry')
        self.assertGreater(sig.tp, sig.entry)
        self.assertEqual(len(sig.tps), 5)

    def test_emoji_only_message_still_gets_a_side(self):
        """Words win, but a message with no direction word falls back to emoji."""
        self.assertEqual(parse_signal('🔴 4400', current_price=4400.0).side,
                         'SELL')
        self.assertEqual(parse_signal('🟢 4400', current_price=4400.0).side,
                         'BUY')


if __name__ == '__main__':
    unittest.main()
