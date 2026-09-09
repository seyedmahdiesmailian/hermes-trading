"""b170 TRADER CODE REVIEW — auto_executor Check 7 (news veto) was wired to a
flag NOBODY PRODUCED, and evaluate_proposal's three Check-1 early returns
shipped without the plural 'reasons' carrier (the b165 defect class, one
module over).

MEASURED BEFORE THE FIX (2026-09-09):
1. `grep -rn blocked_by_macro` over the whole repo: the ONLY writer-side hit
   was the reader itself (auto_executor.py:267) plus b132's source pin. The
   macro veto actually lands through apply_macro_guard's `blocked=True` and
   is then caught by Check 1 — so Check 7's dedicated return could never
   fire, and any future proposal that is vetoed via the flag (rather than
   `blocked`) would silently sail through it.
2. evaluate_proposal returns 21 literal dicts; 3 of them (Check 1:
   no_proposal / no_blueprint / invalid_blueprint) lack 'reasons'. Downstream
   readers use the plural: hermes_runtime copies
   eval_result.get('reasons', []) into proposal['skip_reasons'], and
   signal_listener concatenates it into the ops alert — a vetoed or
   malformed proposal reported an EMPTY reason list.
3. A macro-blocked plan proposal never reached evaluate_proposal at all
   (hermes_runtime gates on `not proposal.get('blocked')`), so a news
   blackout that killed a REAL setup was indistinguishable in the brief
   from "no setup formed".

FIXES:
- engines/macro_filter.apply_macro_guard now sets blocked_by_macro=True
  (additive; `blocked` keeps carrying the veto — nothing removed).
- engines/auto_executor Check 1 returns carry 'reasons' (observability only;
  verdict/reason strings byte-identical).
- hermes_runtime records skip_reason='macro_blackout' + the concrete gate
  reason on a blocked proposal, so the brief/monitor show WHY.

THIS FILE PINS: the producer→reader wiring, the reasons contract via an AST
scan of every literal return (b165 shape, non-vacuous), and the runtime
observability line.
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines.macro_filter import apply_macro_guard, evaluate_macro_filter  # noqa: E402
from engines.auto_executor import evaluate_proposal  # noqa: E402

AE_SRC = os.path.join(ROOT, "engines", "auto_executor.py")
RT_SRC = os.path.join(ROOT, "hermes_runtime.py")


def _blk_pol():
    return {"trade_allowed": True, "regime": "normal",
            "open_positions": 0, "balance": 5000.0}


def _perf():
    return {"daily_pnl": 0.0, "loss_streak": 0, "daily_trades": 0,
            "drawdown_pct": 0.0}


class TestB170ProducerSetsTheFlag(unittest.TestCase):
    def test_guard_sets_blocked_by_macro_alongside_blocked(self):
        out = apply_macro_guard(
            {"blueprint": {}},
            evaluate_macro_filter(
                {"events": [{"title": "FOMC", "impact": "high",
                             "currency": "USD",
                             "date": "2026-09-09T18:00:00+00:00"}]},
                "2026-09-09T18:10:00+00:00"))
        self.assertTrue(out.get("blocked"))
        self.assertTrue(out.get("blocked_by_macro"),
                        "Check 7's flag must have a producer")
        self.assertEqual(out.get("reason"), "high_impact_news_blackout")

    def test_allowed_macro_leaves_both_flags_unset(self):
        out = apply_macro_guard({"blueprint": {}}, {"allowed": True})
        self.assertNotIn("blocked_by_macro", out)
        self.assertNotIn("blocked", out)


class TestB170Check7Live(unittest.TestCase):
    def test_flagged_proposal_is_vetoed_with_its_own_reason(self):
        # a proposal carrying ONLY the flag (not `blocked`) must now be
        # rejected by Check 7 — pre-fix this exact shape executed the rest
        # of the gauntlet and could return execute=True.
        from datetime import datetime, timezone
        import engines.auto_executor as AE
        real_open, real_cd = AE.is_market_open, None
        from engines import cooldown as CD
        real_cd = CD.check_entry_cooldown
        AE.is_market_open = lambda *a, **k: True
        CD.check_entry_cooldown = lambda now=None: {"allowed": True}
        try:
            res = evaluate_proposal(
                {"blueprint": {"side": "BUY", "entry_price": 4000.0,
                               "sl": 3990.0, "tp": 4030.0,
                               "symbol": "XAUUSD"},
                 "grade": "B", "blocked_by_macro": True},
                _blk_pol(), _perf(), {}, None)
            self.assertFalse(res.get("execute"))
            self.assertEqual(res.get("reason"), "macro_blackout")
            self.assertIn("macro_blackout", res.get("reasons", []))
        finally:
            AE.is_market_open = real_open
            CD.check_entry_cooldown = real_cd


class TestB170ReasonsContract(unittest.TestCase):
    """b165 shape: EVERY literal dict returned by evaluate_proposal carries
    'reasons', and the singular headline appears in the list."""

    def _returns(self):
        with open(AE_SRC) as fh:
            tree = ast.parse(fh.read(), filename=AE_SRC)
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "evaluate_proposal")
        out = []
        for node in ast.walk(fn):
            if (isinstance(node, ast.Return)
                    and isinstance(node.value, ast.Dict)):
                out.append(node)
        return out

    def test_scanner_is_not_vacuous(self):
        self.assertGreaterEqual(len(self._returns()), 20,
                                "literal-return census lost rows — "
                                "evaluate_proposal shape changed")

    def test_every_literal_return_carries_reasons(self):
        for node in self._returns():
            keys = {k.value for k in node.value.keys
                    if isinstance(k, ast.Constant)}
            self.assertIn("reasons", keys,
                          f"line {node.lineno}: return without 'reasons' "
                          f"(b165 defect class)")

    def test_check1_reasons_headline_matches_reason(self):
        # blocked proposal: headline must equal the embedded reason, and the
        # plural must contain it (b165 contract).
        res = evaluate_proposal({"blocked": True, "reason": "macro_blackout"},
                                _blk_pol(), _perf(), {}, None)
        self.assertEqual(res["reason"], "macro_blackout")
        self.assertEqual(res["reasons"], ["macro_blackout"])
        res2 = evaluate_proposal({}, _blk_pol(), _perf(), {}, None)
        self.assertEqual(res2["reason"], "no_proposal")
        self.assertEqual(res2["reasons"], ["no_proposal"])


class TestB170RuntimeObservability(unittest.TestCase):
    def test_runtime_records_skip_on_blocked_proposal(self):
        with open(RT_SRC) as fh:
            src = fh.read()
        self.assertIn("proposal['skip_reason'] = 'macro_blackout'", src,
                      "a macro-blocked plan proposal must surface WHY in "
                      "the brief (was indistinguishable from no-setup)")
        self.assertIn("monitor['macro_blocked']", src)


if __name__ == "__main__":
    unittest.main()
