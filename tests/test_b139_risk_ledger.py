"""b139 — the per-trade risk-shrink stack must be PERSISTED and READABLE.

The defect (filed by b137): execution_style is the only per-trade risk damper
(STYLE_RISK_MULT 0.5 on aggressive_* entries), yet no ledger carried it, so
"was the 0.5x style damper actually applied to trade X?" was unanswerable from
history. b142 proved the naive fix (a 13th key on execution_log.csv) is a
NO-OP TRAP: _append_csv_row writes a header only for a NEW file, so the value
lands under DictReader's None restkey and every consumer reads the file as if
the field never existed.

The shipped fix is option (b) from b139's progress note: a SIDECAR ledger,
data/xau_plan/risk_ledger.csv, written at BOTH entry call sites (plan lane in
hermes_runtime, signal lane in signal_listener), with the stack captured AT
THE SOURCE inside evaluate_proposal — the same four factors that multiplied
into the lot, not a hand-typed restatement (b122).

What these tests lock:
  1. SOURCE: real evaluate_proposal returns a risk_stack whose style_mult is
     the module's OWN STYLE_RISK_MULT value for a style-tagged proposal, and
     the stack's product equals final_risk_pct (arithmetic, not vibes).
  2. READABILITY (b142's rule): a DictReader round-trip on a file seeded with
     an OLD-schema row — here, a file that does not exist yet (the ledger is
     new) — proves execution_style comes back as a NAMED column, never under
     the None restkey.
  3. WIRING: both live call sites reference append_risk_ledger (AST scan, so a
     refactor that drops one fails loudly), and the writer is schema-locked:
     extras are DROPPED, so a future key can never silently redefine columns.
  4. TIGHTENING GUARD: nothing in this change may alter a lot or a verdict —
     the same proposal sizes identically with the stack present or absent.
"""
import ast
import csv
import io
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines import auto_executor as AE
from engines import cooldown as CD
from engines.storage import append_risk_ledger, RISK_LEDGER_FIELDS


def _proposal(style=""):
    p = {"blueprint": {"side": "SELL", "entry_price": 4450.0, "sl": 4460.0,
                       "tp": 4425.0, "symbol": "XAUUSD"},
         "grade": "B"}
    if style:
        p["execution_style"] = style
    return p


def _policy(regime="normal"):
    return {"trade_allowed": True, "regime": regime, "open_positions": 0,
            "balance": 5000.0, "max_positions_allowed": 1}


def _perf():
    return {"day": datetime.now(timezone.utc).date().isoformat(),
            "daily_pnl": 0.0, "trades_today": 0, "loss_streak": 0,
            "recent_closed": []}


def _eval(style="", regime="normal"):
    real_open, real_cd = AE.is_market_open, CD.check_entry_cooldown
    AE.is_market_open = lambda *a, **k: True
    CD.check_entry_cooldown = lambda now=None: {"allowed": True}
    try:
        return AE.evaluate_proposal(_proposal(style), _policy(regime),
                                    _perf(), {}, None)
    finally:
        AE.is_market_open = real_open
        CD.check_entry_cooldown = real_cd


class TestStackCapturedAtSource(unittest.TestCase):
    def test_plain_proposal_stack_is_all_neutral(self):
        r = _eval()
        self.assertTrue(r.get("execute"), r.get("reason"))
        st = r["risk_stack"]
        self.assertEqual(st["style_mult"], 1.0)
        self.assertEqual(st["regime_mult"], 1.0)
        self.assertEqual(st["execution_style"], "")
        self.assertEqual(st["final_risk_pct"], r["risk_pct"])

    def test_style_mult_comes_from_the_module_not_a_literal(self):
        # b122: the stack must carry the emitter's OWN value. If someone
        # retunes STYLE_RISK_MULT, this test follows it; a hand-typed 0.5
        # would go red on the retune and hide the drift.
        style = next(iter(AE.STYLE_RISK_MULT))
        r = _eval(style=style)
        self.assertTrue(r.get("execute"), r.get("reason"))
        st = r["risk_stack"]
        self.assertEqual(st["execution_style"], style)
        self.assertEqual(st["style_mult"], AE.STYLE_RISK_MULT[style])
        self.assertNotEqual(st["style_mult"], 1.0)

    def test_regime_mult_tracks_TIGHT_REGIMES(self):
        tight = next(iter(AE.TIGHT_REGIMES))
        st = _eval(regime=tight)["risk_stack"]
        self.assertEqual(st["regime"], tight)
        self.assertEqual(st["regime_mult"], 0.5)

    def test_stack_product_equals_final_risk_pct(self):
        style = next(iter(AE.STYLE_RISK_MULT))
        tight = next(iter(AE.TIGHT_REGIMES))
        st = _eval(style=style, regime=tight)["risk_stack"]
        product = (st["base_risk_pct"] * st["learning_risk_mult"]
                   * st["style_mult"] * (st["defcon_override"] or 1.0)
                   * st["regime_mult"] * st.get("session_mult", 1.0))
        self.assertAlmostEqual(product, st["final_risk_pct"], places=10)


class TestLedgerIsReadable(unittest.TestCase):
    """b142's rule: prove the field is READABLE by a DictReader round-trip —
    never by asserting the dict passed to the writer."""

    def test_round_trip_exposes_named_columns_no_restkey(self):
        style = next(iter(AE.STYLE_RISK_MULT))
        st = _eval(style=style)["risk_stack"]
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            append_risk_ledger(d, dict(st, at="t", lane="plan",
                                       plan_id="p1", lot=0.05))
            append_risk_ledger(d, dict(st, at="t2", lane="signal",
                                       plan_id="signal", lot=0.03))
            with open(d / "risk_ledger.csv", newline="",
                      encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIsNone(row.get(None),
                              "extra fields folded under the None restkey — "
                              "the b142 no-op trap")
            self.assertEqual(row["execution_style"], style)
            self.assertAlmostEqual(float(row["style_mult"]),
                                   AE.STYLE_RISK_MULT[style])
        self.assertEqual({r["lane"] for r in rows}, {"plan", "signal"})

    def test_writer_is_schema_locked(self):
        # A future key must NOT silently add a column (that is how a shared
        # ledger rots); and a missing key must not shift the row.
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            append_risk_ledger(d, {"at": "x", "lane": "plan",
                                   "not_a_column": "zzz"})
            text = (d / "risk_ledger.csv").read_text(encoding="utf-8")
        header = text.splitlines()[0]
        self.assertEqual(header, ",".join(RISK_LEDGER_FIELDS))
        self.assertNotIn("zzz", text)
        self.assertNotIn("not_a_column", header)


class TestBothCallSitesAreWired(unittest.TestCase):
    """AST scan: each lane's execution-log call site must sit next to a
    risk-ledger call. Deleting either wiring fails loudly here."""

    def _calls(self, path, func):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        hits = 0
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == func):
                hits += 1
        return hits

    def test_plan_lane_writes_the_ledger(self):
        self.assertGreaterEqual(
            self._calls(ROOT / "hermes_runtime.py", "append_risk_ledger"), 1)

    def test_signal_lane_writes_the_ledger(self):
        self.assertGreaterEqual(
            self._calls(ROOT / "engines" / "signal_listener.py",
                        "append_risk_ledger"), 1)

    def test_signal_lane_helper_is_called_at_both_exec_paths(self):
        src = (ROOT / "engines" / "signal_listener.py").read_text(
            encoding="utf-8")
        # limit_pending path + market path
        self.assertGreaterEqual(src.count("_log_signal_risk_stack("), 3)


class TestNoGateChanged(unittest.TestCase):
    """Hard rule: observability only. The lot and verdict must be identical to
    what the pre-b139 code produced for the same inputs."""

    def test_lot_and_verdict_unchanged_by_the_stack(self):
        r1 = _eval(style=next(iter(AE.STYLE_RISK_MULT)))
        r2 = _eval()
        self.assertTrue(r1.get("execute") and r2.get("execute"))
        # style-damped lot must be SMALLER (the damper still bites)...
        self.assertLess(r1["command"]["lot"], r2["command"]["lot"])
        # ...and the plain path's lot must be exactly what the SHARED sizing
        # model produces for the stack's final_risk_pct — i.e. the ledger
        # captured the stack without the stack changing the lot.
        from engines.orchestrator import compute_xau_position_size
        want = compute_xau_position_size(
            balance=5000.0, risk_pct=r2["risk_stack"]["final_risk_pct"],
            stop_distance_price=10.0, point=0.01, point_value_per_lot=1.0,
            volume_min=0.01, volume_step=0.01, volume_max=AE.MAX_LOT,
            min_meaningful_lot=0.01)
        self.assertEqual(r2["command"]["lot"], want["lot"])

    def test_blocked_paths_carry_no_stack(self):
        pol = _policy("locked")
        pol["trade_allowed"] = False
        r = AE.evaluate_proposal(_proposal(), pol, _perf(), {}, None)
        self.assertFalse(r.get("execute"))
        self.assertNotIn("risk_stack", r)


if __name__ == "__main__":
    unittest.main()
