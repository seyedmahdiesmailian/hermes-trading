"""b143 — the risk ledger gets a READER, and the reader must be honest.

b139 shipped the sidecar (data/xau_plan/risk_ledger.csv); b143's rule is that
an unread ledger is theatre. This test locks the reader's contract:

  1. ARITHMETIC — a coherent row reconciles; a row whose recorded
     final_risk_pct disagrees with the product of its own legs is flagged
     product_mismatch (mutation test: flip one leg, the reader must see it).
  2. MONEY — the lot is re-sized through the SHARED model
     (engines.orchestrator.compute_xau_position_size), never a restatement:
     a lot ABOVE the stack's authorization is a defect in either lane, and a
     lot BELOW it is only excused on the signal lane (post-stack channel cap,
     defect (b) in the script docstring).
  3. CENT ROUNDING — risk_usd is stored rounded to cents, so the derived
     balance carries error; a row that sits exactly on a volume-step boundary
     must still read coherent (the band check), not a false alarm.
  4. THE JOIN — plan-lane rows join to a ticket and aggregate EVERY close-deal
     row of a partially-closed position (sum, not last); signal-lane rows
     report joinable=False with an explicit reason instead of a guessed match
     (defect (a): the sidecar has no ticket column).
  5. HONEST ZERO — a missing/empty ledger yields rows=0 and NO_ROWS_YET; the
     reader never fabricates a row.
  6. READ-ONLY — the module imports no bridge/order surface at all.
"""
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import b143_risk_ledger_reader as R  # noqa: E402
from engines.storage import RISK_LEDGER_FIELDS  # noqa: E402


def _row(**over):
    """A coherent plan-lane row: 0.0105 base x 0.5 style = 0.0052525... no —
    keep the arithmetic EXACT: base 0.0105, style 0.5, defcon None, regime 1.0
    -> final 0.00525. balance 5000 -> risk_usd 26.25 (exact cents). stop 10.0
    -> 1000 points -> raw lot 0.02625 -> stepped 0.02."""
    row = {"at": "2026-09-08T04:30:00+00:00", "lane": "plan",
           "plan_id": "xau-test01", "side": "SELL", "lot": "0.02",
           "entry": "3600.0", "sl": "3610.0", "tp": "3575.0", "grade": "B",
           "base_risk_pct": "0.0105", "learning_risk_mult": "1.0",
           "execution_style": "aggressive_retest", "style_mult": "0.5",
           "defcon_override": "None", "regime": "normal", "regime_mult": "1.0",
           "final_risk_pct": "0.00525", "risk_usd": "26.25"}
    row.update(over)
    return row


def _write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(RISK_LEDGER_FIELDS))
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in RISK_LEDGER_FIELDS})


class TestArithmetic(unittest.TestCase):
    def test_coherent_row_reconciles(self):
        rec = R.reconcile(_row())
        self.assertEqual(rec["status"], "coherent", rec)
        self.assertAlmostEqual(rec["stack_product"], 0.00525, places=12)

    def test_mutated_leg_is_product_mismatch(self):
        bad = _row(style_mult="0.6")  # legs say 0.0063, final still 0.00525
        self.assertEqual(R.reconcile(bad)["status"], "product_mismatch")

    def test_restkey_row_is_unparseable_not_silent(self):
        row = _row()
        row["_restkey"] = ["junk"]
        self.assertEqual(R.reconcile(row)["status"], "unparseable")


class TestMoney(unittest.TestCase):
    def test_lot_above_stack_authorization_is_defect(self):
        self.assertEqual(R.reconcile(_row(lot="0.03"))["status"],
                         "lot_above_model")

    def test_lot_below_model_signal_lane_is_capped_not_defect(self):
        rec = R.reconcile(_row(lane="signal", plan_id="signal", lot="0.01"))
        self.assertEqual(rec["status"], "lot_below_model_signal_capped")

    def test_lot_below_model_plan_lane_is_defect(self):
        self.assertEqual(R.reconcile(_row(lot="0.01"))["status"],
                         "lot_below_model")

    def test_cent_rounding_on_step_boundary_is_not_false_alarm(self):
        # balance 5000 x 0.00525 = 26.25 exact; make risk_usd land so the
        # derived balance sits a cent-rounding hair under a step boundary:
        # recorded lot 0.02 must stay coherent even though mid-band sizes to
        # 0.01 (raw 0.019999...). The band check must save it.
        row = _row(risk_usd="26.24")  # mid balance 4998.1 -> raw 0.01999
        rec = R.reconcile(row)
        self.assertEqual(rec["status"], "coherent", rec)

    def test_sizing_model_is_imported_not_restated(self):
        src = (ROOT / "scripts" / "b143_risk_ledger_reader.py").read_text()
        self.assertIn("from engines.orchestrator import compute_xau_position_size", src)
        # no hand-rolled floor() sizing formula in the reader
        self.assertNotIn("raw_lot", src)


class TestJoin(unittest.TestCase):
    def _journal(self, tmp):
        p = Path(tmp) / "trade_journal.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["ticket", "close_time", "side",
                                              "volume", "price", "profit",
                                              "comment", "journaled_at",
                                              "position_id", "commission",
                                              "swap"])
            w.writeheader()
            # partially closed position: TWO close deals on one position_id
            w.writerow({"ticket": "5001", "close_time": "1760000000",
                        "side": "SELL", "volume": "0.01", "price": "3590",
                        "profit": "10.00", "comment": "", "journaled_at": "",
                        "position_id": "9001", "commission": "-0.5",
                        "swap": "0.0"})
            w.writerow({"ticket": "5002", "close_time": "1760000500",
                        "side": "SELL", "volume": "0.01", "price": "3585",
                        "profit": "5.00", "comment": "", "journaled_at": "",
                        "position_id": "9001", "commission": "0.0",
                        "swap": "-0.2"})
        return p

    def test_plan_lane_joins_and_sums_close_deals(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = R.read_journal_tickets(self._journal(tmp))
            exec_rows = [{"at": "2026-09-08T04:30:05+00:00",
                          "plan_id": "xau-test01", "side": "SELL",
                          "lot": "0.02", "risk_usd": "26.25",
                          "result_ok": "True", "ticket": "9001"}]
            out = R.join_to_tickets([_row()], exec_rows, journal)
            self.assertEqual(len(out), 1)
            self.assertTrue(out[0]["joinable"], out[0])
            self.assertEqual(out[0]["ticket"], "9001")
            self.assertEqual(out[0]["close_deals"], 2)
            # 10 + 5 profit, -0.5 + 0 commission, 0 - 0.2 swap
            self.assertAlmostEqual(out[0]["realized_net"], 14.3, places=4)

    def test_signal_lane_reports_unjoinable_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = R.read_journal_tickets(self._journal(tmp))
            out = R.join_to_tickets([_row(lane="signal", plan_id="signal")],
                                    [], journal)
            self.assertFalse(out[0]["joinable"])
            self.assertIn("not unique", out[0]["join_error"])

    def test_old_era_ticket_key_still_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "j.csv"
            with open(p, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["ticket", "close_time",
                                                  "side", "volume", "price",
                                                  "profit", "comment",
                                                  "journaled_at", "position_id",
                                                  "commission", "swap"])
                w.writeheader()
                w.writerow({"ticket": "777", "close_time": "1750000000",
                            "side": "BUY", "volume": "0.02", "price": "3300",
                            "profit": "-4.0", "comment": "", "journaled_at": "",
                            "position_id": "", "commission": "0", "swap": "0"})
            journal = R.read_journal_tickets(p)
            exec_rows = [{"at": "x", "plan_id": "xau-test01", "side": "SELL",
                          "lot": "0.02", "risk_usd": "26.25",
                          "result_ok": "True", "ticket": "777"}]
            out = R.join_to_tickets([_row()], exec_rows, journal)
            self.assertTrue(out[0]["joinable"], out[0])
            self.assertAlmostEqual(out[0]["realized_net"], -4.0, places=4)


class TestHonestZero(unittest.TestCase):
    def test_missing_ledger_is_zero_rows_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(R.read_ledger(Path(tmp) / "nope.csv"), [])
            d = R.derive([], [], {})
            self.assertEqual(d["rows"], 0)
            self.assertEqual(d["verdict"], "NO_ROWS_YET")

    def test_derive_counts_and_mix(self):
        rows = [_row(), _row(plan_id="xau-test02", lane="signal",
                             style_mult="1.0", execution_style="",
                             final_risk_pct="0.0105", risk_usd="52.50",
                             lot="0.05")]
        d = R.derive(rows, [], {})
        self.assertEqual(d["status_counts"].get("coherent"), 2, d)
        mix = d["damper_mix"]
        self.assertEqual(mix["damper_fire_counts"]["style"],
                         {"fires": 1, "neutral": 1})
        self.assertEqual(mix["combined_factor_distribution"],
                         {"0.5x": 1, "1.0x": 1})

    def test_double_charge_counter_matches_b138_definition(self):
        rows = [_row(regime="defensive", defcon_override="0.5",
                     regime_mult="0.5", final_risk_pct="0.002625",
                     risk_usd="13.13")]
        d = R.derive(rows, [], {})
        self.assertEqual(d["damper_mix"]["double_charge_rows_b138"], 1)


class TestReadOnly(unittest.TestCase):
    def test_module_never_touches_the_bridge(self):
        src = (ROOT / "scripts" / "b143_risk_ledger_reader.py").read_text()
        for needle in ("bridge_client", "BridgeClient", "requests", "urllib",
                       "open_position", "close_position"):
            self.assertNotIn(needle, src)

    def test_artifact_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.json"
            old = R.OUT
            try:
                R.OUT = out
                led = R.main()
            finally:
                R.OUT = old
            self.assertTrue(out.exists())
            for key in ("rows", "execution_log", "journal_rows",
                        "journal_positions", "_derived"):
                self.assertIn(key, led)


if __name__ == "__main__":
    unittest.main()
