"""b165 TRADER CODE REVIEW — evaluate_signal's early-return paths shipped
without the 'reasons' key that every other path and every downstream consumer
uses.

MEASURED BEFORE THE FIX (live journal data/signals/signals_log.json, 52 rows):
1 row carried a singular 'reason' ('high_impact_news_blackout') and NO
'reasons' — the macro/news blackout early return. The other three early
returns (unsupported_symbol, low_signal_confidence, invalid_direction) have
never fired inside the 200-entry rolling window, so they are latent.

VICTIMS (all read the plural, none the singular):
  * signal_daemon.py:111  ', '.join(se.get('reasons', [])[:3])  -> ''
  * hermes_runtime.py:746 proposal['skip_reasons'] = ...get('reasons', [])
  * notifier/dashboards.py:1279 (dec.get('reasons') or [''])[0] -> ''
  * scripts/b163_plan_age_census.py align_of(dec.get('reasons') or [])
    -> ('none', 0.0): a blackout-era decision would be censused as if Check 4
    never ran.
A macro blackout is exactly the window where the operator asks WHY nothing
traded, and the ops panel answered with an empty string.

FIX (observability only — verdict, score and reason are byte-identical):
all four early-return dicts now carry 'reasons' alongside 'reason', with
'reason' kept for its two readers (test_failclosed_news_spread, legacy
account-policy copy).

THIS FILE PINS THE CONTRACT, statically and dynamically, per b106's shape:
every literal return dict of evaluate_signal must carry BOTH keys, the
singular must appear in the plural list (so no reader can be misled about
which reason is the headline), and the scanner must not be vacuous.
"""
import ast
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines.signal_decision import evaluate_signal  # noqa: E402

SRC = os.path.join(ROOT, "engines", "signal_decision.py")


def _src():
    with open(SRC) as fh:
        return fh.read()


def _return_dicts(src_text, fname="signal_decision.py"):
    """Every literal dict returned directly from evaluate_signal's body
    (nested functions excluded)."""
    tree = ast.parse(src_text, filename=fname)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "evaluate_signal")
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.FunctionDef) and node is not fn:
            continue  # do not descend into nested defs (there are none today)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            out.append(node.value)
    return out


def _keys(d):
    return {k.value for k in d.keys if isinstance(k, ast.Constant)}


class TestB165EarlyReturnContract(unittest.TestCase):
    def test_b165_scanner_actually_finds_every_return_path(self):
        # anti-vacuity: the gate has 5 return paths and the census of the
        # module counts them; if a sixth return is added this fires first.
        rets = _return_dicts(_src())
        self.assertEqual(len(rets), 5,
                         "evaluate_signal's return-path census changed — "
                         "review the new path against this contract")

    def test_b165_every_return_carries_both_reason_keys(self):
        for d in _return_dicts(_src()):
            keys = _keys(d)
            self.assertIn("reasons", keys,
                          "a return path ships without 'reasons' — the "
                          "journal, daemon alert, ops panel and b163 census "
                          "all read the plural (b165)")
        # the early returns ALSO carry the singular 'reason' for its two
        # readers (test_failclosed_news_spread + risk.py policy copy); the
        # fall-through return is plural-only and must stay that way.
        early = [d for d in _return_dicts(_src()) if "reason" in _keys(d)]
        self.assertEqual(len(early), 4,
                         "return-path shape changed: 4 early returns carry "
                         "'reason', the final one does not")

    def test_b165_singular_reason_is_a_member_of_the_plural_list(self):
        # a reader that takes reasons[0] and one that takes 'reason' must
        # never disagree about the headline.
        cases = [
            # (signal, hermes, policy, macro) tuples below
            ({"symbol": "BTCUSD", "side": "BUY", "entry": 1, "sl": 1,
              "tp": 2, "confidence": 0.8, "rr_ratio": 2.0, "warnings": []},
             {"bias": "neutral"},
             {"trade_allowed": True, "regime": "normal", "open_positions": 0},
             None),
            ({"symbol": "XAUUSD", "side": "BUY", "entry": 1, "sl": 1,
              "tp": 2, "confidence": 0.1, "rr_ratio": 2.0, "warnings": []},
             {"bias": "neutral"},
             {"trade_allowed": True, "regime": "normal", "open_positions": 0},
             None),
            ({"symbol": "XAUUSD", "side": "HOLD", "entry": 1, "sl": 1,
              "tp": 2, "confidence": 0.8, "rr_ratio": 2.0, "warnings": []},
             {"bias": "neutral"},
             {"trade_allowed": True, "regime": "normal", "open_positions": 0},
             None),
            ({"symbol": "XAUUSD", "side": "BUY", "entry": 2595, "sl": 2590,
              "tp": 2610, "confidence": 0.8, "rr_ratio": 3.0, "warnings": []},
             {"bias": "bullish"},
             {"trade_allowed": True, "regime": "normal", "open_positions": 0},
             {"allowed": False, "reason": "high_impact_news_blackout"}),
        ]
        for sig, hermes, policy, macro in cases:
            r = evaluate_signal(sig, hermes, policy, macro_filter=macro)
            self.assertIn("reasons", r, f"no reasons for {sig['symbol']}")
            self.assertTrue(r["reasons"], "reasons must be non-empty")
            self.assertIn(r["reason"], r["reasons"],
                          f"headline '{r['reason']}' absent from "
                          f"{r['reasons']} — readers would disagree")

    def test_b165_news_blackout_path_keeps_its_score_and_verdict(self):
        # the fix must be observability-only: the blackout return's other
        # fields are byte-identical to pre-fix behaviour.
        sig = {"symbol": "XAUUSD", "side": "BUY", "entry": 2595, "sl": 2590,
               "tp": 2610, "confidence": 0.8, "rr_ratio": 3.0,
               "warnings": []}
        policy = {"trade_allowed": True, "regime": "normal",
                  "open_positions": 0}
        r = evaluate_signal(sig, {"bias": "bullish"}, policy,
                            macro_filter={"allowed": False,
                                          "reason": "high_impact_news_blackout"})
        self.assertEqual(r["verdict"], "skip")
        self.assertEqual(r["score"], 7.5)  # 1+2+1+2+1.5 pre-macro, uncapped
        self.assertFalse(r["trade_allowed"])
        self.assertIn("high_impact_news_blackout", r["reasons"])

    def test_b165_live_journal_rows_after_fix_all_have_reasons(self):
        # the shipped ledger: only rows written BY THIS CODE must be complete;
        # older rows are evidence of the gap, not a violation. We pin the
        # newest 10 rows (all post-fix era going forward once daemons reload).
        path = os.path.join(ROOT, "data", "signals", "signals_log.json")
        if not os.path.exists(path):
            self.skipTest("no journal on this machine")
        with open(path) as fh:
            rows = json.load(fh)
        self.assertIsInstance(rows, list)
        # NOTE (2026-09-08): pre-restart rows legitimately lack 'reasons' —
        # the daemons run the boot-time tree (b116). This asserts only the
        # SHAPE the new writer emits, verified against a live call above;
        # it exists to fail loudly if someone re-gutters the key.
        offenders = [r["timestamp"] for r in rows
                     if isinstance(r.get("decision"), dict)
                     and "reason" in r["decision"]
                     and "reasons" not in r["decision"]
                     and r["timestamp"] >= "2026-09-09"]
        self.assertEqual(offenders, [],
                         "rows written after the b165 landing without "
                         "'reasons' — the fix regressed")


if __name__ == "__main__":
    unittest.main()
