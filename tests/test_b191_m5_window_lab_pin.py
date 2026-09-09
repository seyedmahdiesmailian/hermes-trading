"""b191 — SPARED-DIRECTION PIN for the widening parked in the b190 round.

The b190 ledger's test file records, in its module docstring, the sentence
'FOLLOW-UP FILED AS b191' (quoted here, so it reads as a mention, not a
second claim): the TRUE live-parity merit bar would be an M5 ENTRY stream
over window-independent legs, and that lab does not exist yet. b102's rule
says such a parked widening must have a test that pins the SPARED shape —
the one that fails loudly if someone quietly ships the lab without editing
this pin, and fails loudly if someone deletes the pin without shipping.

What is spared (measured, not argued):
  * scripts/b191_m5_window_lab.py does not exist — no M5-entry window legs
    have been priced;
  * the citable wired bar is still the b190 coverage-gated one: quotable on
    cached/W1/W2 only, W3/W4 refused (M5 history cap, coverage 0.72/0.00).

When b191 ships, this file is EDITED, not deleted: flip the existence
assert into a citation of the new ledger and re-quote the band in the
backlog item in the same commit.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest",
                      "b190_merit_bar_live_trigger.json")
LAB = os.path.join(ROOT, "scripts", "b191_m5_window_lab.py")

if not os.path.exists(LEDGER):
    raise unittest.SkipTest(
        f"{LEDGER} missing — run scripts/b190_merit_bar_live_trigger.py")


class TestB191SparedDirection(unittest.TestCase):
    def setUp(self):
        with open(LEDGER) as fh:
            self.led = json.load(fh)

    def test_b191_m5_entry_window_lab_is_not_wired_yet(self):
        """The spared half of b190's follow-up: no M5-entry window lab exists.
        If this goes RED because the file appeared, b191 is shipping — EDIT
        this pin to certify the new ledger (and re-quote the band), never
        just delete it."""
        self.assertFalse(
            os.path.exists(LAB),
            "scripts/b191_m5_window_lab.py appeared while the b191 backlog "
            "item is still todo — the M5-entry window legs must be priced, "
            "the band re-quoted, and this pin edited (not deleted)")

    def test_b191_cited_bar_is_still_the_coverage_gated_b190_one(self):
        """The bar every round compares against is the b190 wired bar — and
        it is only quotable on the three legs with real M5 closes. If b191's
        lab changes the band, it changes HERE, in the open."""
        bar = self.led["_merit_bar_live_wired"]
        quotable = {k: bar.get(k) for k in ("cached", "W1", "W2", "W3", "W4")}
        self.assertEqual([quotable[k] is not None
                          for k in ("cached", "W1", "W2")], [True, True, True],
                         f"covered legs lost their citation: {quotable}")
        self.assertEqual([quotable[k] for k in ("W3", "W4")], [None, None],
                         "an uncovered leg became quotable without a "
                         "coverage re-measurement (b116 class)")
        vals = [round(float(quotable[k]), 3) for k in ("cached", "W1", "W2")]
        self.assertEqual(vals, [0.28, 0.197, 0.245],
                         "the cited ~0.20-0.28 band moved — re-quote every "
                         "backlog note that uses it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
