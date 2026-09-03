"""b71 — the lab harness must make the round-6 artefact IMPOSSIBLE to repeat.

Root cause (b68 round 6): every lab script hand-rolled r_stats() and called
backtest_ohlc WITHOUT time_stop_bars, so dayext_cont_w10 printed exp_R +1.096
— the best number any arm ever produced — while its mean hold was 87 M15 bars
(max 520 = 5+ days). Under the live 36h time_exit it is +0.787 on n=41. The
second failure mode (b69 class): an arm with risk<=0 geometry drops every
signal silently and trades:0 reads as "no edge" when nothing was measured.

Pins, in order of what would rot first:

1. THE SHIPPED RECHECK JSON (data/backtest/b71_harness_recheck.json): every
   arm row carries a ladder_ts row AND the hold columns (mean/p95/max bars +
   holds_over_time_exit). This is the "FAIL the round's own summary if mean
   hold > time exit without a time-stopped re-measurement" clause, made
   structural: the harness cannot produce a row without them.
2. The w10 artefact itself: ladder exp_R - ladder_ts exp_R > 0.15 and ladder
   mean hold > the time exit — the exact numbers that motivated b71, replayed
   from the shipped JSON (not recomputed here, so the test stays fast).
3. run_arm derives the time exit from the LIVE guard + the dataset's bar
   spacing (M15 -> 144, M5 -> 432), never a hardcoded 144.
4. A zero-trade row must carry a named zero_reason (diagnose verdict), and
   diagnose() must name the b69 dead-arm shape (invalid_geometry) and the
   never_fired shape on synthetic arms.
5. check_honesty fires on each of the three dishonest row shapes and stays
   silent on an honest one (anti-vacuity both directions).
"""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engines import lab_harness as lh  # noqa: E402
from engines.legacy_guards import MAX_POSITION_AGE_HOURS  # noqa: E402

RECHECK = os.path.join(ROOT, "data", "backtest", "b71_harness_recheck.json")
ARMS = ("dayext_cont_w10", "dayext_cont_a10", "dayext_cont_w10_e25",
        "dayext_cont_a10_e25", "dayext_fade_a10")


def _load():
    with open(RECHECK) as f:
        return json.load(f)


class TestShippedRecheck(unittest.TestCase):
    def test_every_arm_row_has_ladder_ts_and_hold_columns(self):
        # The b71 contract: no exp_R may be quoted from a row that lacks the
        # live-time-exit measurement or the hold statistics.
        res = _load()
        limit = res["_time_stop_bars"]
        self.assertEqual(limit, int(MAX_POSITION_AGE_HOURS * 3600 // 900))
        for arm in ARMS:
            row = res[arm]
            self.assertIn("ladder_ts", row, f"{arm}: no time-stopped row")
            self.assertEqual(row["_time_stop_bars"], limit)
            for mode in ("plain", "ladder", "ladder_ts"):
                s = row[mode]
                self.assertGreater(s["trades"], 0, f"{arm}:{mode} fired 0")
                for col in ("mean_hold_bars", "p95_hold_bars",
                            "max_hold_bars", "holds_over_time_exit"):
                    self.assertIn(col, s, f"{arm}:{mode} missing {col}")
                    self.assertIsNotNone(s[col])

    def test_w10_artefact_is_visible_in_the_shipped_numbers(self):
        # The round-6 headline (+1.096) collapses under the live time exit;
        # the shipped recheck must keep that visible so nobody re-quotes the
        # ladder number as a candidate.
        res = _load()
        w = res["dayext_cont_w10"]
        limit = w["_time_stop_bars"]
        # the swing signature lives in the hold TAIL (mean 87.5 < 144 but
        # p95 248, max 520 bars) — the harness must flag it via p95 too.
        self.assertGreater(w["ladder"]["p95_hold_bars"], limit,
                           "the artefact's swing-hold signature must remain")
        self.assertGreater(w["ladder"]["exp_R"] - w["ladder_ts"]["exp_R"], 0.15)
        self.assertAlmostEqual(w["ladder"]["exp_R"], 1.096, places=3)
        self.assertAlmostEqual(w["ladder_ts"]["exp_R"], 0.787, places=3)
        # the ATR-stop arms are intraday-shaped: hold well inside the exit
        a = res["dayext_cont_a10"]
        self.assertLess(a["ladder"]["mean_hold_bars"], limit)
        self.assertEqual(a["ladder"]["exp_R"], a["ladder_ts"]["exp_R"])

    def test_honesty_summary_names_the_artefact_arm(self):
        res = _load()
        complaints = res["_honesty_complaints"]
        self.assertTrue(any("dayext_cont_w10" in c for c in complaints),
                        "the round's own summary must flag the w10 headline")
        self.assertFalse(any("dayext_cont_a10:" in c for c in complaints),
                         "an intraday-shaped arm must not be flagged")


class TestTimeExitDerivation(unittest.TestCase):
    def test_m15_and_m5_get_the_same_36_hours(self):
        rows_m15 = [{"time": 1784109600 + 900 * i} for i in range(50)]
        rows_m5 = [{"time": 1784109600 + 300 * i} for i in range(50)]
        self.assertEqual(lh.live_time_stop_bars(rows_m15), 144)
        self.assertEqual(lh.live_time_stop_bars(rows_m5), 432)

    def test_weekend_gap_does_not_break_spacing(self):
        # 10 bars at 900s, a 3-day gap, 10 more — median spacing stays 900.
        rows = [{"time": 1784109600 + 900 * i} for i in range(10)]
        rows += [{"time": 1784109600 + 900 * 9 + 259200 + 900 * i}
                 for i in range(1, 11)]
        self.assertEqual(lh.bar_seconds(rows), 900)


class TestDiagnose(unittest.TestCase):
    def test_never_fired_arm_names_itself(self):
        rows = [{"time": 0, "open": 1, "high": 1, "low": 1, "close": 1}]
        d = lh.diagnose(rows, lambda r: None)
        self.assertIn("never_fired", d["verdict"])
        self.assertEqual(d["signals"], 0)

    def test_dead_geometry_arm_names_the_b69_shape(self):
        # A fade arm with a LEVEL-anchored stop: SELL whose sl < entry ->
        # risk <= 0 -> backtest_ohlc silently drops every signal.
        def bad(row):
            return {"side": "SELL", "entry": 100.0, "sl": 99.0, "tp": 97.0}
        rows = [{"time": i, "open": 100, "high": 101, "low": 99,
                 "close": 100} for i in range(5)]
        d = lh.diagnose(rows, bad)
        self.assertEqual(d["signals"], 5)
        self.assertEqual(d["invalid_geometry"], 5)
        self.assertIn("invalid_geometry", d["verdict"])
        self.assertIn("b69", d["verdict"])

    def test_raising_arm_is_a_named_finding_not_a_crash(self):
        def boom(row):
            raise KeyError("tp")
        d = lh.diagnose([{"time": 0}], boom)
        self.assertIn("raised", d["verdict"])

    def test_run_arm_attaches_zero_reason(self):
        rows = [{"time": 1784109600 + 900 * i, "open": 100, "high": 101,
                 "low": 99, "close": 100} for i in range(200)]
        out = lh.run_arm(rows, lambda r: None)
        self.assertEqual(out["ladder"]["trades"], 0)
        self.assertIn("never_fired", out["zero_reason"])


class TestCheckHonesty(unittest.TestCase):
    def _good_ts(self, exp=0.5, hold=5):
        return {"trades": 100, "exp_R": exp, "mean_hold_bars": hold}

    def test_fires_on_each_dishonest_shape(self):
        # zero trades without a reason
        c = lh.check_honesty("a", {"ladder": {"trades": 0}})
        self.assertTrue(any("zero_reason" in x for x in c))
        # no ladder_ts row at all
        c = lh.check_honesty("b", {"ladder": self._good_ts()})
        self.assertTrue(any("b71" in x for x in c))
        # swing hold under the time exit limit
        row = {"ladder": self._good_ts(hold=200),
               "ladder_ts": self._good_ts(), "_time_stop_bars": 144}
        c = lh.check_honesty("c", row)
        self.assertTrue(any("swing position" in x for x in c))
        # hold TAIL swing-shaped while the mean is fine (the real w10 shape:
        # mean 87.5 < 144 but p95 248) — b71 must catch it via p95 too
        tail = dict(self._good_ts(hold=87), p95_hold_bars=248)
        row = {"ladder": tail, "ladder_ts": self._good_ts(),
               "_time_stop_bars": 144}
        c = lh.check_honesty("c2", row)
        self.assertTrue(any("hold TAIL" in x for x in c))
        # headline moves > 0.15R under the time exit (the w10 shape)
        row = {"ladder": self._good_ts(exp=1.096, hold=87),
               "ladder_ts": self._good_ts(exp=0.787), "_time_stop_bars": 144}
        c = lh.check_honesty("d", row)
        self.assertTrue(any("quote the ts number" in x for x in c))

    def test_stays_silent_on_an_honest_row(self):
        row = {"ladder": self._good_ts(exp=0.327),
               "ladder_ts": self._good_ts(exp=0.327), "_time_stop_bars": 144}
        self.assertEqual(lh.check_honesty("ok", row), [])


class TestHarnessIsNotLivePath(unittest.TestCase):
    def test_no_live_module_imports_lab_harness(self):
        # Read-only research code: the LIVE trading path (root *.py entrypoints
        # + engines/ + notifier/) must never depend on the lab harness — same
        # isolation the b68 lab scripts keep. scripts/ is research/ops tooling
        # and MAY import it (b71_recheck_round6.py does, by design).
        import ast
        targets = ([os.path.join(ROOT, f) for f in os.listdir(ROOT)
                    if f.endswith(".py")]
                   + [p for base in ("engines", "notifier")
                      for root, _dirs, files in os.walk(os.path.join(ROOT, base))
                      for p in (os.path.join(root, fn) for fn in files)
                      if p.endswith(".py")])
        offenders = []
        for p in targets:
            if os.path.basename(p) == "lab_harness.py":
                continue
            tree = ast.parse(open(p).read(), filename=p)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(
                        a.name.split(".")[0] == "engines" and
                        "lab_harness" in a.name for a in node.names):
                    offenders.append(p)
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if mod == "engines.lab_harness" or (
                            mod == "engines" and any(
                                a.name == "lab_harness" for a in node.names)):
                        offenders.append(p)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
