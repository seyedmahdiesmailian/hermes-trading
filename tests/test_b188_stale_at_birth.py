"""b188(a) contract: stale-at-birth directional plans are forced neutral."""
import unittest
from hermes_runtime import _stale_at_birth


class StaleAtBirth(unittest.TestCase):
    def test_bullish_below_invalidation_is_stale(self):
        self.assertTrue(_stale_at_birth("bullish", 4000, 3999))
        self.assertTrue(_stale_at_birth("bullish", 4000, 4000))

    def test_bullish_above_invalidation_is_fresh(self):
        self.assertFalse(_stale_at_birth("bullish", 4000, 4001))

    def test_bearish_mirror(self):
        self.assertTrue(_stale_at_birth("bearish", 4000, 4001))
        self.assertFalse(_stale_at_birth("bearish", 4000, 3999))

    def test_neutral_never_stale(self):
        self.assertFalse(_stale_at_birth("neutral", 4000, 9999))

    def test_junk_fails_open_to_original_bias(self):
        self.assertFalse(_stale_at_birth("bullish", None, 4000))
        self.assertFalse(_stale_at_birth("bullish", 4000, None))
        self.assertFalse(_stale_at_birth("bullish", "x", "y"))
        self.assertFalse(_stale_at_birth("bullish", 0, 4000))


if __name__ == "__main__":
    unittest.main()
