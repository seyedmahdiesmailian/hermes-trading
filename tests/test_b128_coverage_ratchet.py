#!/usr/bin/env python3
"""b128 — THE COVERAGE RATCHET: every frozen-ledger producer must be registered.

The rule (from b127's own diff): a script that writes a ledger under
data/backtest|data/ops must have a reproduction check in CHECKS, or be listed
in BASELINE_UNCOVERED as known debt. The debt list can only SHRINK — a new
producer that is not registered turns the ratchet red, and burning an old token
down (registering its check) turns it red if the baseline is not trimmed in the
same commit. b136 is the first burned-down token: its derive() now reproduces
from the 244 embedded walk rows.

Read-only: the scanner parses the registry with ast and stats scripts/*.py; it
imports no bridge client, calls no order endpoint. The two synthetic-tree tests
write only inside a TemporaryDirectory.

NAME-CARRIER for b128 (b102's discipline).
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from scripts import b127_producer_reproduction as b127    # noqa: E402

_REAL_REGISTRY = open(os.path.join(_ROOT, "scripts",
                                   "b127_producer_reproduction.py")).read()


def _fake_tree(tmp: str, producer_src: str,
               owned_art: str | None = None) -> str:
    """Lay out a minimal repo-shaped tree the scanner can run against:
    one producer script (token b999), optionally its owned artifact, and a
    copy of the real registry (so _registered_tokens works unchanged)."""
    os.makedirs(os.path.join(tmp, "scripts"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "data", "backtest"), exist_ok=True)
    with open(os.path.join(tmp, "scripts", "b999_debt.py"), "w") as fh:
        fh.write(producer_src)
    if owned_art:
        with open(os.path.join(tmp, "data", "backtest", owned_art), "w") as fh:
            fh.write("{}")
    with open(os.path.join(tmp, "scripts",
                           "b127_producer_reproduction.py"), "w") as fh:
        fh.write(_REAL_REGISTRY)
    return tmp


class TestB128CoverageRatchet(unittest.TestCase):

    def test_b128_scan_matches_baseline_on_real_tree(self) -> None:
        """The live scan and the frozen debt list must agree EXACTLY: no new
        unregistered producer, no registered-but-still-listed token."""
        u = b127.uncovered_writers()
        self.assertEqual([t for t in u if t not in b127.BASELINE_UNCOVERED], [],
                         "unregistered ledger producer(s) — register a check")
        self.assertEqual([t for t in b127.BASELINE_UNCOVERED if t not in u], [],
                         "stale baseline entry — trim the burned-down token")
        # the scan is deterministic across runs
        self.assertEqual(u, b127.uncovered_writers())

    def test_b128_ratchet_has_teeth_new_unregistered_producer_is_red(self) -> None:
        """A producer writing its own artifact, absent from the baseline,
        must be flagged — the exact failure mode b128 exists to stop."""
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp,
                       'import json\njson.dump({}, open("b999_art.json"))\n',
                       "b999_art.json")
            u = b127.uncovered_writers(root=tmp)
            self.assertEqual(u, ["b999"],
                             "scanner missed an unregistered owned-writer")
            self.assertNotIn("b999", b127.BASELINE_UNCOVERED,
                             "b999 must not be in the real baseline")
            with self.assertRaises(AssertionError) as cm:
                b127.check_b128_coverage_ratchet(root=tmp)
            self.assertIn("b999", str(cm.exception))

    def test_b128_read_only_reference_is_not_a_producer(self) -> None:
        """Ownership rule: a script that merely READS another round's ledger
        (b77/b92 reading b68l_independent_windows.json) must not be counted
        as its writer."""
        with tempfile.TemporaryDirectory() as tmp:
            src = ('import json\n'
                   'led = json.load(open("b68l_independent_windows.json"))\n'
                   'json.dump(led, open("summary_unmatched.json", "w"))\n')
            _fake_tree(tmp, src, None)
            self.assertNotIn("b999", b127.uncovered_writers(root=tmp))

    def test_b128_registered_producer_leaves_the_scan(self) -> None:
        """The burn-down half: with a check function named check_b999_* LISTED
        in CHECKS, the token vanishes from the scan — so the only way to clear
        a new token is to register it, never to extend the baseline silently."""
        with tempfile.TemporaryDirectory() as tmp:
            _fake_tree(tmp,
                       'import json\njson.dump({}, open("b999_art.json"))\n',
                       "b999_art.json")
            self.assertIn("b999", b127.uncovered_writers(root=tmp))
            reg_path = os.path.join(tmp, "scripts",
                                    "b127_producer_reproduction.py")
            with open(reg_path) as fh:
                reg = fh.read()
            self.assertIn("    check_b128_coverage_ratchet,\n)", reg)
            reg = reg.replace(
                "    check_b128_coverage_ratchet,\n)",
                "    check_b128_coverage_ratchet,\n    check_b999_artifact,\n)")
            reg += "\n\ndef check_b999_artifact() -> str:\n    return 'b999'\n"
            with open(reg_path, "w") as fh:
                fh.write(reg)
            self.assertNotIn("b999", b127.uncovered_writers(root=tmp),
                             "registered producer still reported uncovered")

    def test_b128_stale_baseline_entry_is_red(self) -> None:
        """A token listed in BASELINE that the scan no longer reports (a
        registration without a trim) must fire the stale arm."""
        orig = b127.BASELINE_UNCOVERED
        try:
            b127.BASELINE_UNCOVERED = orig + ("b999notreal",)
            with self.assertRaises(AssertionError) as cm:
                b127.check_b128_coverage_ratchet()
            self.assertIn("b999notreal", str(cm.exception))
        finally:
            b127.BASELINE_UNCOVERED = orig

    def test_b128_burned_down_b136_is_registered_and_reproduces(self) -> None:
        """b136: neither in the scan nor the baseline, IS registered, and its
        derive() reproduces _derived exactly from the 244 embedded rows."""
        u = b127.uncovered_writers()
        self.assertNotIn("b136", u)
        self.assertNotIn("b136", b127.BASELINE_UNCOVERED)
        self.assertIn("b136", b127._registered_tokens())
        labels = [fn.__name__ for fn in b127.CHECKS]
        self.assertIn("check_b136_derived_blocks", labels)
        self.assertIn("check_b128_coverage_ratchet", labels)
        label = b127.check_b136_derived_blocks()
        self.assertIn("244", label)
        self.assertIn("ALL_EMITTABLE_REGIMES_WIRED", label)

    def test_b128_no_gate_and_no_write(self) -> None:
        """The ratchet must never touch the trade path: the script contains no
        order endpoint calls, and the scan writes nothing."""
        src = _REAL_REGISTRY
        for forbidden in ("send_order", "close_position", "modify_position",
                          "partial_close"):
            self.assertNotIn(forbidden, src)
        before = sorted(os.listdir(os.path.join(_ROOT, "data", "backtest")))
        b127.uncovered_writers()
        after = sorted(os.listdir(os.path.join(_ROOT, "data", "backtest")))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
