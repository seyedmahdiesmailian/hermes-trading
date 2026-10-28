"""b267: unit tests pinning the M5 confirmation length semantics.

The sweeps (ab_b239, b265, b266) read M5_CONFIRM_CLOSES as a count of closes,
but a length of 1 has no adjacent pair, so `all(range(0))` == True and every
single bar passed — a silently unconditional trigger. That is why the "1" row
of the sweep looked like the best setting on paper.

m5_confirmation now floors the length at 2, so the shortest non-degenerate
confirmation is one close-to-close move. These tests pin that floor.
"""
import os
import unittest
from importlib import reload

from engines.orchestrator import _closes, m5_confirmation


def _rows(values):
    return [{"time": i * 300, "high": v + 1, "low": v - 1, "close": v}
            for i, v in enumerate(values)]


class CloseCountSemantics(unittest.TestCase):
    """The setting counts CLOSES; moves are one fewer."""

    def test_two_closes_is_one_move(self):
        self.assertTrue(m5_confirmation(_rows([100, 101]), "bullish"))
        self.assertFalse(m5_confirmation(_rows([101, 100]), "bullish"))
        self.assertTrue(m5_confirmation(_rows([101, 100]), "bearish"))

    def test_flat_closes_fail_closed(self):
        self.assertFalse(m5_confirmation(_rows([100, 100]), "bullish"))
        self.assertFalse(m5_confirmation(_rows([100, 100]), "bearish"))

    def test_single_close_never_confirms(self):
        # this is the regression: previously one close gave all([]) == True
        self.assertFalse(m5_confirmation(_rows([100]), "bullish"))
        self.assertFalse(m5_confirmation(_rows([100]), "bearish"))

    def test_length_of_one_still_observes_a_move(self):
        # the floor makes the setting behave as 2 closes, not as an empty check
        import engines.orchestrator as O
        original = O.M5_CONFIRM_CLOSES
        try:
            O.M5_CONFIRM_CLOSES = 1
            self.assertTrue(O.m5_confirmation(_rows([100, 101]), "bullish"))
            self.assertFalse(O.m5_confirmation(_rows([101, 100]), "bullish"))
            self.assertFalse(O.m5_confirmation(_rows([100]), "bullish"))
        finally:
            O.M5_CONFIRM_CLOSES = original

    def test_span_matches_the_setting(self):
        import engines.orchestrator as O
        original = O.M5_CONFIRM_CLOSES
        try:
            for k in (2, 3, 5):
                O.M5_CONFIRM_CLOSES = k
                self.assertEqual(len(_closes(_rows(list(range(50))), k)), k)
                self.assertEqual(_closes(_rows(list(range(k - 1))), k), [])
        finally:
            O.M5_CONFIRM_CLOSES = original


class EnvOverride(unittest.TestCase):
    def test_env_override_applies(self):
        import engines.orchestrator as O
        original = O.M5_CONFIRM_CLOSES
        try:
            os.environ["HERMES_M5_CONFIRM_CLOSES"] = "3"
            reload(O)
            self.assertEqual(O.M5_CONFIRM_CLOSES, 3)
            self.assertTrue(O.m5_confirmation(_rows([1, 2, 3]), "bullish"))
            self.assertFalse(O.m5_confirmation(_rows([3, 2, 3]), "bullish"))
        finally:
            os.environ.pop("HERMES_M5_CONFIRM_CLOSES", None)
            reload(O)
            self.assertEqual(O.M5_CONFIRM_CLOSES, original)


if __name__ == "__main__":
    unittest.main()
