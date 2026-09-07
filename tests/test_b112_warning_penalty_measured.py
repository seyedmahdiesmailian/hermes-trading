"""b112 — THE SIGNAL GATE PENALISES A WARNING FAMILY THAT HAS NEVER FIRED.
DECIDED 2026-09-06: DO NOT add the penalty. These tests pin WHY.

b106 filed b112 from a census measured by re-parsing the journal's raw_text
OFFLINE (parse_signal(raw) with no price). That frame is not the frame
production runs in: the live listener always passes the real tick
(current_price>0 whenever the market is open), and the parser's `_gold_abbrev`
branch then defaults a number-only message to XAUUSD instead of emitting
no_symbol_found. scripts/b112_warning_frame_probe.py re-measured all 29
journal signals in BOTH frames through the real parser + real gate:

  LIVE frame (what the gate actually sees):  symbol_defaulted_xauusd 15/29,
      no_symbol_found 0, sl_* 0.
  OFFLINE frame (b106's census):             symbol_defaulted_xauusd 4,
      no_symbol_found 11 — and every one of those 11 has symbol=="" →
      is_valid False → the listener `continue`s BEFORE evaluate_signal.
      They never reach the gate at all.

So b112's premise was wrong in both directions:
  (a) no_symbol_found is an OFFLINE MEASUREMENT ARTIFACT — a message with no
      symbol and no gold-looking number is dropped upstream by `is_valid`,
      so penalising it in the gate would penalise an unreachable population;
  (b) the defaulted family, the one that DOES reach the gate (52% of it),
      was priced two ways and the penalty fails both:
      - COST: every penalty scheme (−0.5, −1.0, Check-1-half) flips exactly
        1/29 signals (idx 0, score 6.0 → 5.5). The two signals that actually
        executed in production (idx 4, 9) do NOT flip — under the current
        parser + bias-on-record recheck they don't even clear the gate
        (4: direction_conflict, 9: poor_rr_0.5 after the b74 ladder fix).
      - BENEFIT: the defaulted legs look worse in the channel replay
        (0.105R vs 0.125R avg, WR 53.6% vs 70.7%) but the populations are
        CHANNEL-CONFOUNDED: 664/707 filled defaulted legs come from one
        channel (radin main) which contributes only 3 named-gold legs.
        Within the channels that carry both populations there is NO usable
        comparison: goldfree's defaulted side is n=6 (noise), olivex's is
        n=0 filled. The warning is a property of the CHANNEL's posting
        style, not of the trade's quality.

DECISION (this item's own rule: measure before tightening): no gate change.
The Check-8 clause stays sl_-scoped — it is dead-but-harmless (it fires only
if the parser flags impossible SL geometry, which is correct behaviour even
though the sample is 0 so far). The b106 spared-direction pin in
test_b106_parser_decision_contract.py keeps guarding against a side-effect
widening; this file pins the EVIDENCE so the decision cannot be re-litigated
from the stale offline census.

FRAME RULE (reusable, filed as b113): a census that feeds a gate decision
must be measured in the frame the gate runs in. parse_signal(text) with no
price is a different PARSER, not the same parser on different data — the
price argument switches branches (_gold_abbrev, _resolve_ladder). Any
offline re-parse of a live journal must state which frame it emulates and
check which warnings are frame-only.
"""
from __future__ import annotations

import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_FRAME = os.path.join(ROOT, "data", "backtest", "b112_warning_frame.json")
LEDGER_PERF = os.path.join(ROOT, "data", "backtest",
                           "b112_defaulted_performance.json")


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class TestB112FrameArtifact(unittest.TestCase):
    """The offline no_symbol_found family never reaches the gate live."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER_FRAME):
            raise unittest.SkipTest("b112 frame ledger missing — run "
                                    "scripts/b112_warning_frame_probe.py")
        cls.d = _load(LEDGER_FRAME)

    def test_b112_no_symbol_found_is_never_seen_by_the_live_gate(self):
        # The live-frame census (current parser + real price) has ZERO
        # no_symbol_found; the offline census has 11. That gap is the
        # artifact b112 was filed on.
        self.assertNotIn("no_symbol_found", self.d["census_live_frame_current_parser"])
        self.assertGreater(self.d["census_offline_frame_b106"].get("no_symbol_found", 0), 0)

    def test_b112_every_offline_no_symbol_signal_fails_is_valid(self):
        # The mechanism, pinned per-signal: offline symbol=="" → the
        # listener's `if not parsed.is_valid: continue` drops it before
        # evaluate_signal. If a future parser gives such a message a symbol,
        # this fires and the artifact claim must be re-checked.
        from engines.signal_parser import Signal
        self.assertFalse(Signal(symbol="", side="BUY", entry=4000.0).is_valid)
        for r in self.d["rows"]:
            if "no_symbol_found" in r["offline_warnings"]:
                self.assertEqual(r["offline_symbol"], "",
                                 "offline no_symbol_found but symbol non-empty — "
                                 "frame artifact claim needs re-measuring")

    def test_b112_the_price_argument_switches_the_branch(self):
        # Same text, two frames, two warning families — the proof that the
        # offline census is not "the same parser on different data".
        from engines.signal_parser import parse_signal
        text = "خرید \n4560\nحد ضرر\n4550\nحد سود\n4590"
        off = parse_signal(text)
        live = parse_signal(text, current_price=4555.0)
        self.assertIn("symbol_defaulted_xauusd", off.warnings)
        self.assertIn("symbol_defaulted_xauusd", live.warnings)
        # A number-ONLY short form: offline cannot default (no gold-range
        # number), live can (the price proves the market).
        short = "82 و 72 خرید\nاستاپ 62\nتی پی 92 ، 502"
        off2 = parse_signal(short)
        live2 = parse_signal(short, current_price=4482.0)
        self.assertIn("no_symbol_found", off2.warnings)
        self.assertNotIn("no_symbol_found", live2.warnings)
        self.assertEqual(live2.symbol, "XAUUSD")

    def test_b113_a_frame_census_must_record_both_frames_side_by_side(self):
        # b113's own rule, pinned on the ledger that produced it: a census
        # that feeds a gate decision must record the frame the gate runs in
        # AND the frame the measurement was taken in, so the reader can see
        # the artifact instead of inheriting it. If a future probe drops one
        # of the frames, this fires.
        for key in ("census_live_frame_current_parser",
                    "census_offline_frame_b106", "census_logged_frame"):
            self.assertIn(key, self.d, f"ledger lost {key} — b113's rule is "
                                       "that the frames stay comparable")
        # and they must actually DIFFER, or the double measurement is theatre
        self.assertNotEqual(self.d["census_live_frame_current_parser"],
                            self.d["census_offline_frame_b106"])

    def test_b112_defaulted_is_the_only_warning_family_that_reaches_the_gate(self):
        c = self.d["census_live_frame_current_parser"]
        self.assertEqual(self.d["n_defaulted_live"], c.get("symbol_defaulted_xauusd"))
        self.assertGreaterEqual(self.d["defaulted_share_of_gate_reachable"], 0.4,
                                "defaulted family shrank below 40% of gate-reachable — "
                                "b112's cost/benefit sample has moved, re-measure")


class TestB112PenaltyFailsBothWays(unittest.TestCase):
    """Cost: 1 flip. Benefit: confounded, not one-sided. No change ships."""

    @classmethod
    def setUpClass(cls):
        if not (os.path.exists(LEDGER_FRAME) and os.path.exists(LEDGER_PERF)):
            raise unittest.SkipTest("b112 ledgers missing")
        cls.frame = _load(LEDGER_FRAME)
        cls.perf = _load(LEDGER_PERF)

    def test_b112_the_penalty_flips_exactly_one_journal_signal(self):
        flips = self.frame["counterfactual_flips"]
        self.assertEqual(set(flips), {"defaulted_minus_0.5", "defaulted_minus_1.0",
                                      "check1_half_on_default"})
        for name, v in flips.items():
            self.assertEqual(v["execute_before"] - v["execute_after"], 1,
                             f"{name}: flip count moved off 1/29 — re-read b112 "
                             "before quoting its cost")

    def test_b112_the_two_signals_that_executed_would_not_flip(self):
        # idx 4 and 9 are the journal's two 'execute' rows. Under the current
        # parser they don't clear the gate even WITHOUT the penalty, so the
        # penalty's production cost on the executed book is zero.
        rows = {r["i"]: r for r in self.frame["rows"]}
        for i in (4, 9):
            self.assertEqual(rows[i]["logged_verdict"], "execute")
            self.assertNotEqual(rows[i].get("cf_verdict"), "execute",
                                f"signal {i} now clears the gate un-penalised — "
                                "b112's zero-cost-on-executed-book claim is stale")

    def test_b112_the_raw_performance_gap_is_channel_confound(self):
        # Raw: defaulted looks worse. Honest: the defaulted book is ONE
        # channel (radin main 664/707 legs) vs 3 named legs in that channel.
        tag = self.perf["by_tag"]
        self.assertLess(tag["defaulted"]["avg_usd_tp1"], tag["named_gold"]["avg_usd_tp1"])
        radin = self.perf["within_channel_both_populations"]["replay.csv"]
        self.assertLess(radin["named_gold"]["filled"], 10,
                        "radin main now has a real named-gold population — the "
                        "confound may be gone, re-run the benefit analysis")

    def test_b112_within_channel_no_population_survives_the_test(self):
        # Every channel that carries BOTH populations fails to support a
        # tightening: radin main has 664 defaulted vs 3 named legs (no
        # control), goldfree has 6 defaulted vs 213 named (worse, but n=6
        # is noise), olivex has 0 FILLED defaulted legs (nothing to
        # compare). If any population grows past these floors the honest
        # answer may change — this test fires and forces a re-measure.
        w = self.perf["within_channel_both_populations"]
        radin = w["replay.csv"]
        self.assertLess(radin["named_gold"]["filled"], 10)
        gf = w["replay_goldfree.csv"]
        self.assertLessEqual(gf["defaulted"]["filled"], 20,
                             "goldfree defaulted sample grew past noise — "
                             "the within-channel test is finally possible")
        ox = w["replay_olivex.csv"]
        self.assertEqual(ox["defaulted"]["filled"], 0,
                         "olivex defaulted legs now fill — re-run the "
                         "within-channel comparison before quoting b112")

    def test_b112_the_gate_clause_remains_sl_scoped(self):
        # The shipped state: unchanged. b106's spared-direction pin guards
        # the widening; this pin guards the DECISION RECORD itself.
        with open(os.path.join(ROOT, "engines", "signal_decision.py")) as fh:
            src = fh.read()
        self.assertIn('"sl_" in w', src)
        self.assertNotIn("symbol_defaulted", src,
                         "b112 decided NO penalty; if this ships, ship it as its "
                         "own measured round and update these pins to certify it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
