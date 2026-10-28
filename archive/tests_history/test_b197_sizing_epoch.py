"""b197 — the tiered base (b196) must be SELF-EXPLAINING in ops reporting.

b196 wired the account's balance-tiered base_risk_pct into entry sizing.
The consequence b196's own filing named: the FIRST balance>=5000 entry runs
a 25% smaller lot than every pre-fix trade, and until this item the only
place that revealed it was the raw base_risk_pct column in
risk_ledger.csv — 18 rows deep, nobody reads it raw. This test locks the
fix's contract:

  1. CLASSIFIER — sizing_epoch() buckets a row as tiered / max_flat /
     tier_mismatch / unknown from its OWN recorded fields, importing the
     tier table and the ceiling (never restating them — b143's own rule).
  2. ROUNDING — risk_usd is cent-rounded and final_risk_pct 4dp, so the
     derived balance can land a hair across a tier edge; b143's lo/mid/high
     band rule must save such a row (a false 'tier_mismatch' on healthy
     data is exactly the noise that trains operators to ignore the line).
  3. SUMMARY — counts, per-lane split, the honest 'no tiered row yet'
     qualifier, and the WARNING that fires on a real torn row.
  4. PERSIAN LINE — empty on zero rows (never fabricate), explanatory when
     only max_flat rows exist.
  5. DIGEST WIRING — autopilot_digest renders the line through the CANONICAL
     reader (import, not re-parse), inside a b49 selfcheck-guarded block,
     and its --self-check passes end-to-end on the real ledger.
  6. LEDGER CONTRACT — derive() carries the sizing_epoch block, so the
     b127 producer-reproduction check (extended same commit) can demand it.
"""
import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import b143_risk_ledger_reader as R  # noqa: E402
from engines.auto_executor import MAX_RISK_PER_TRADE_PCT  # noqa: E402
from engines.risk import _base_risk_pct  # noqa: E402


def _row(**over):
    """A coherent plan-lane row, 1500<=balance<5000 -> base == MAX (today's
    live shape); tests override base/risk fields to reach other buckets."""
    row = {"at": "2026-09-09T18:15:02+00:00", "lane": "plan",
           "plan_id": "xau-b197", "side": "BUY", "lot": "0.03",
           "entry": "4420.0", "sl": "4414.0", "tp": "4431.0", "grade": "B",
           "base_risk_pct": "0.02", "learning_risk_mult": "1.0",
           "execution_style": "pullback_continuation", "style_mult": "1.0",
           "defcon_override": "None", "regime": "normal", "regime_mult": "1.0",
           "final_risk_pct": "0.02", "risk_usd": "80.0"}
    row.update(over)
    return row


def _tiered_row():
    """balance >= 5000 post-b196: base 0.015, final 0.015, risk_usd 90.00
    -> implied balance exactly 6000."""
    return _row(base_risk_pct="0.015", final_risk_pct="0.015",
                risk_usd="90.00", lot="0.04")


class TestClassifier(unittest.TestCase):
    def test_max_base_is_max_flat(self):
        self.assertEqual(R.sizing_epoch(_row()), "max_flat")

    def test_sub_max_base_matching_tier_is_tiered(self):
        self.assertEqual(R.sizing_epoch(_tiered_row()), "tiered")
        # the <800 tier: 1% base, implied balance 700
        row = _row(base_risk_pct="0.01", final_risk_pct="0.01",
                   risk_usd="7.00")
        self.assertEqual(R.sizing_epoch(row), "tiered")

    def test_base_matching_no_tier_is_loud(self):
        # 1.1% is not a tier at any balance — torn row or moved table.
        row = _row(base_risk_pct="0.011", final_risk_pct="0.011",
                   risk_usd="66.00")
        self.assertEqual(R.sizing_epoch(row), "tier_mismatch")

    def test_missing_or_zero_base_is_unknown_not_guessed(self):
        self.assertEqual(R.sizing_epoch(_row(base_risk_pct="")), "unknown")
        self.assertEqual(R.sizing_epoch(_row(base_risk_pct="0")), "unknown")
        self.assertEqual(R.sizing_epoch({}), "unknown")

    def test_class_imports_policy_never_restates_it(self):
        """The classifier must READ the tier table and the ceiling from the
        shipped modules — a hand-copied 0.01/0.015/0.02 ladder is the exact
        drift the b193/b189 parity class punishes."""
        src = (ROOT / "scripts" / "b143_risk_ledger_reader.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "sizing_epoch")
        body = ast.unparse(fn)
        self.assertIn("_base_risk_pct", body)
        self.assertIn("MAX_RISK_PER_TRADE_PCT", body)
        for literal in ("0.015", "0.01 ", "'0.01'", "\"0.01\""):
            self.assertNotIn(literal, body,
                             f"tier literal {literal!r} restated in the "
                             "classifier instead of imported")


class TestRoundingBand(unittest.TestCase):
    def test_cent_rounding_across_tier_edge_stays_tiered(self):
        """risk_usd cent-rounding moves the implied balance: base 0.015 is
        only valid at [800,1500) OR >=5000; an implied 799.9 from rounding
        must NOT read as tier_mismatch when the band reaches 800+."""
        # real 800.4-tiered case: final pct 0.0075, risk_usd rounds to 6.00
        row = _row(base_risk_pct="0.015", final_risk_pct="0.0075",
                   risk_usd="5.99")  # implied 798.667, band +/- 0.667 -> 800+
        self.assertEqual(R.sizing_epoch(row), "tiered")

    def test_band_does_not_smoke_over_a_real_mismatch(self):
        # 0.011 sits 0.001 off the nearest tier — a full band (~0.7$ of
        # balance, i.e. never 0.1% of risk) cannot bridge it.
        row = _row(base_risk_pct="0.011", final_risk_pct="0.011",
                   risk_usd="88.00")
        self.assertEqual(R.sizing_epoch(row), "tier_mismatch")


class TestSummary(unittest.TestCase):
    def test_counts_and_per_lane(self):
        s = R.sizing_epoch_summary([_row(), _row(lane="signal"),
                                    _tiered_row()])
        self.assertEqual(s["counts"]["max_flat"], 2)
        self.assertEqual(s["counts"]["tiered"], 1)
        self.assertEqual(s["counts"]["tier_mismatch"], 0)
        self.assertTrue(s["tiered_rows_present"])
        self.assertEqual(s["per_lane"]["signal"], {"max_flat": 1})
        self.assertEqual(s["first_tiered_at"],
                         "2026-09-09T18:15:02+00:00")

    def test_all_max_flat_is_explained_not_blamed(self):
        """Today's honest live state: pre-b196 rows and sub-5000 rows share
        base=MAX — the note must SAY that instead of implying the wire is
        dead (b194's ALIVE_AND_INERT ambiguity, reported proactively)."""
        s = R.sizing_epoch_summary([_row()])
        self.assertFalse(s["tiered_rows_present"])
        self.assertIn("no tiered row yet", s["note"])

    def test_tier_mismatch_raises_warning_in_note(self):
        s = R.sizing_epoch_summary([_row(base_risk_pct="0.011",
                                         final_risk_pct="0.011",
                                         risk_usd="66.00")])
        self.assertIn("WARNING", s["note"])

    def test_persian_line_honest_zero(self):
        self.assertEqual(R.persian_sizing_line(R.sizing_epoch_summary([])),
                         "")

    def test_persian_line_explains_small_lots(self):
        line = R.persian_sizing_line(R.sizing_epoch_summary([_row()]))
        self.assertIn("سقف ثابت", line)
        self.assertIn("طبیعی", line)
        line2 = R.persian_sizing_line(R.sizing_epoch_summary([_tiered_row()]))
        self.assertIn("سیاست پله‌ای", line2)


class TestLedgerContract(unittest.TestCase):
    def test_derive_carries_the_block(self):
        d = R.derive([_row(), _tiered_row()], [], {})
        self.assertIn("sizing_epoch", d)
        self.assertEqual(d["sizing_epoch"]["counts"]["tiered"], 1)

    def test_real_ledger_rows_all_classify_cleanly(self):
        """The shipped live sidecar (6+ rows, all pre-5000) must classify
        with zero unknown/mismatch — the reader's first real data is its
        regression sample."""
        # WP1: risk_ledger.csv is untracked live state — no sidecar on a bare
        # checkout. The pure-logic half stays covered by
        # test_derive_carries_the_block (synthetic rows); this live-rows half
        # skips where there is no live box to regress against.
        if not R.LEDGER.exists():
            self.skipTest("no live risk_ledger on this checkout")
        rows = R.read_ledger()
        buckets = {R.sizing_epoch(r) for r in rows}
        self.assertTrue(rows, "live risk_ledger vanished — investigate, "
                              "do not delete this test")
        self.assertLessEqual(buckets, {"max_flat", "tiered"},
                             f"unexpected bucket(s) {buckets} on live rows")


class TestDigestWiring(unittest.TestCase):
    def test_digest_reads_through_the_canonical_reader(self):
        src = (ROOT / "scripts" / "autopilot_digest.py").read_text()
        self.assertIn("b143_risk_ledger_reader", src)
        self.assertIn("sizing epoch section", src)  # b49 guard name
        # no re-parse of the CSV inside the digest (one-definition rule)
        self.assertNotIn("risk_ledger.csv", src)

    def test_digest_selfcheck_end_to_end(self):
        # WP1: this test asserts the sizing line RENDERS, which needs live
        # ledger rows (untracked state). Bare checkouts skip; graceful
        # degradation without a ledger stays covered by
        # test_digest_survives_broken_ledger_read.
        if not R.LEDGER.exists():
            self.skipTest("no live risk_ledger on this checkout")
        env = dict(os.environ)
        env["AUTOPILOT_REPORT_BOT_TOKEN"] = "123:fake-b197-token"
        r = subprocess.run([sys.executable, "scripts/autopilot_digest.py",
                            "--self-check"],
                           capture_output=True, text=True, timeout=120,
                           env=env, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0,
                         "--self-check must be loud, not silent: "
                         + r.stderr[-600:])
        # the live ledger has rows, so the sizing line must render
        self.assertIn("پایه ریسک", r.stdout)

    def test_digest_survives_broken_ledger_read(self):
        """The digest's sizing section is one guard block: in NORMAL mode a
        broken read must stay silent-but-rc=0 (b49's contract), under
        --self-check it must go LOUD. Simulate by replacing the canonical
        reader's read_ledger with a raiser (the exact shape of "the ledger
        moved/rotted" that the guard must survive silently in prod and shout
        about under --self-check).
        """
        seam_note = "probe: canonical reader raises"
        env = {**os.environ, "AUTOPILOT_REPORT_BOT_TOKEN": "",
               "TELEGRAM_BOT_TOKEN": ""}  # b46 rule: BOTH empty — the
        # digest's `or` fallback would otherwise pick the live .env token and
        # really page the ops chat from a test run.
        # Patch the SAME module identity the digest imports
        # (`from scripts import b143_risk_ledger_reader`). Note: patching the
        # LEDGER constant does NOT work — read_ledger's default arg bound it
        # at def-time — so the function itself is replaced (and the digest
        # calls it with no explicit path).
        probe = ("import sys; sys.path.insert(0, '.');"
                 "from scripts import b143_risk_ledger_reader as b;"
                 "b.read_ledger = lambda *a, **k: (_ for _ in ()).throw("
                 "RuntimeError('%s'));"
                 "src = open('scripts/autopilot_digest.py').read();") % seam_note
        # Normal mode: still exits 0 — the guard swallows, digest prints
        r = subprocess.run(
            [sys.executable, "-c",
             probe + "g = {'__file__': 'scripts/autopilot_digest.py',"
                     " '__name__': '__main__'};"
                     " exec(compile(src, 'scripts/autopilot_digest.py',"
                     " 'exec'), g)"],
            capture_output=True, text=True, timeout=120, env=env,
            cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertNotIn("پایه ریسک", r.stdout)  # swallowed: line absent
        # --self-check mode: the same breakage must be LOUD
        r2 = subprocess.run(
            [sys.executable, "-c",
             probe + "sys.argv.append('--self-check');"
                     "g = {'__file__': 'scripts/autopilot_digest.py',"
                     " '__name__': '__main__'};"
                     " exec(compile(src, 'scripts/autopilot_digest.py',"
                     " 'exec'), g)"],
            capture_output=True, text=True, timeout=120,
            env={**env, "AUTOPILOT_REPORT_BOT_TOKEN": "123:fake"},
            cwd=str(ROOT))
        self.assertNotEqual(r2.returncode, 0,
                            "a swallowed ledger error must be loud "
                            "under --self-check (b49)")
        self.assertIn("sizing epoch section", r2.stderr)

if __name__ == "__main__":
    unittest.main()
