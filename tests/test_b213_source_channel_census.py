"""b213 — pin the source-channel findings AND the reason nothing is wired.

The valuable claim here is a NEGATIVE one: selecting channels on a noisy
half-sample loses money out-of-sample, so the source term stays out of
evaluate_signal until the pre-registered close condition fires. A negative
claim rots silently, so it gets the same pins as a positive one.

These tests also guard the ARCHITECTURAL fact that motivated the census:
the decision path currently has no source-channel term at all. If someone
wires one, these tests must be revisited deliberately rather than by
accident.
"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import b213_source_channel_census as C  # noqa: E402


class LedgerReproduces(unittest.TestCase):
    """b127 discipline: the producer must rebuild its own ledger."""

    @classmethod
    def setUpClass(cls):
        cls.led = C.main(write=False)

    def test_self_check_is_clean(self):
        self.assertEqual(self.led["_self_check_problems"], [])

    def test_every_channel_has_a_sample(self):
        self.assertEqual(len(self.led["per_channel"]), 7)
        for ch, s in self.led["per_channel"].items():
            self.assertGreater(s["n"], 0, ch)


class WinRateIsNotExpectancy(unittest.TestCase):
    """The trap this census exists to expose, as an assertion."""

    @classmethod
    def setUpClass(cls):
        cls.per = C.main(write=False)["per_channel"]

    def test_gtmofx_wins_most_signals_and_still_loses_money(self):
        g = self.per["gtmofx"]
        self.assertGreater(g["win_pct"], 70.0)
        self.assertLess(g["total"], 0.0,
                        "gtmofx stopped being the win-rate trap — re-read b213")

    def test_that_loss_is_explained_by_payoff_not_by_luck(self):
        g = self.per["gtmofx"]
        self.assertLess(g["payoff"], 0.5)
        self.assertLessEqual(g["t_stat"], -2.0)

    def test_olivex_is_the_mirror_image(self):
        """Wins 14% of the time and is still not a loser — same lesson."""
        o = self.per["olivex"]
        self.assertLess(o["win_pct"], 20.0)
        self.assertGreater(o["payoff"], 3.0)


class SelectionOnNoiseFailsOutOfSample(unittest.TestCase):
    """THE reason the source term is not wired. Do not delete lightly."""

    @classmethod
    def setUpClass(cls):
        cls.led = C.main(write=False)

    def test_naive_positive_half_selection_loses(self):
        naive = self.led["out_of_sample"]["naive_positive_half_rule"]
        self.assertLess(
            naive["delta"], 0,
            "picking channels on the first half beat trading everything — "
            "the b213 'stay unwired' verdict needs re-deriving")

    def test_channels_flip_sign_between_halves(self):
        self.assertGreaterEqual(
            len(self.led["sign_flips"]), 2,
            "channel PnL became stable across halves — revisit the close "
            "condition, the instability argument no longer holds")

    def test_tightening_only_veto_convicts_nobody_on_half_sample(self):
        """A stricter rule is honest precisely because it does nothing."""
        veto = self.led["out_of_sample"]["tightening_only_loser_veto"]
        self.assertEqual(veto["vetoed_on_first_half"], [])
        self.assertEqual(veto["delta"], 0.0)


class GoldfreeIsTheOnlyStableEdge(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.led = C.main(write=False)

    def test_goldfree_is_significant(self):
        self.assertGreaterEqual(self.led["per_channel"]["goldfree"]["t_stat"], 2.0)

    def test_goldfree_is_positive_in_every_quartile(self):
        qs = self.led["quartiles"]["goldfree"]
        self.assertEqual(len(qs), 4)
        for q in qs:
            self.assertGreater(q["total"], 0, f"quartile {q['from']} went negative")

    def test_goldfree_does_not_flip_sign(self):
        self.assertNotIn("goldfree", self.led["sign_flips"])


class SourceIsStillNotWired(unittest.TestCase):
    """Guards the architectural premise of the census."""

    def test_evaluate_signal_has_no_source_term(self):
        src = (ROOT / "engines" / "signal_decision.py").read_text(encoding="utf-8")
        for token in ("source_channel", "channel_weight", "source_score"):
            self.assertNotIn(
                token, src,
                f"{token} appeared in signal_decision — a source term was "
                "wired; b213's close condition must be checked first")

    def test_parser_does_not_extract_the_forwarder_prefix(self):
        src = (ROOT / "engines" / "signal_parser.py").read_text(encoding="utf-8")
        self.assertNotIn("source_channel", src)


class StatsAreArithmetic(unittest.TestCase):
    """The helper must not drift into a different definition."""

    def test_t_stat_matches_the_textbook_formula(self):
        seg = [("d", 1.0), ("d", 2.0), ("d", 3.0), ("d", 4.0)]
        s = C.stats(seg)
        avg = 2.5
        sd = math.sqrt(sum((p - avg) ** 2 for _, p in seg) / 3)
        self.assertAlmostEqual(s["avg"], avg, places=6)
        self.assertAlmostEqual(s["t_stat"], round(avg / (sd / 2), 2), places=2)

    def test_empty_segment_is_zero_not_a_crash(self):
        self.assertEqual(C.stats([])["n"], 0)

    def test_skipped_rows_are_excluded(self):
        """Skipped signals were never traded; counting them measures fiction."""
        chans = C.load_channels()
        self.assertIn("otsfx", chans)
        # otsfx has 35 raw rows but only 7 that were actually taken
        self.assertLess(len(chans["otsfx"]), 20)


if __name__ == "__main__":
    unittest.main()
