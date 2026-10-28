"""b68 round 15 (b68o) — previous-TRADING-WEEK high/low breakout.

Round 14 closed the screening era with the note that future rounds must
justify themselves before burning a draw; this round's candidate is the one
LEVEL family never measured — PWH/PWL, the higher-timeframe analogue of the
loop's only twice-replicated arm (pdh_break_w10). Geometry is round 4's
CLOSE-CONFIRMED level break lifted verbatim, one timeframe up.

Pinned OFFLINE from synthetic datasets (the week-level builder, the
close-confirmation geometry, the rebind discipline) and from the SHIPPED
ledgers (data/backtest/b68o_weekly_lab.json + b68o_weekly_confirm.json):
- trading-week semantics: DAY_SHIFT (00:xx bars belong to the previous
  day, so a Monday 00:30 bar is still in the PREVIOUS ISO week);
- build_week_levels: a week's level comes ONLY from the previous week's
  bars; the dataset's first week and holiday-stub weeks never become a
  level (no stale carry-over across legs — b76's contamination class);
- pwh_break_at is a PURE function of (rows, levels, i): close-through with
  the prior bar on the other side, entry next OPEN, SL stop_atr*ATR beyond
  the broken level, TP 2R, mirror for the low;
- rebind() rebuilds levels for the new dataset (never stale);
- the shipped cached lab ledger: b71 harness contract on both arms, no
  honesty complaints, and the round's disclosure fact — the cached leg's
  signals are ALL BUY (24/24): the recent regime only broke weekly HIGHS,
  so cached numbers for this arm are one-sided by construction;
- the shipped confirm ledger: every independent leg has ZERO overlap with
  the cached span (b76), the funnel rows reproduce round 14's shipped
  ledger exactly on W1..W4 (same bars, same harness — drift is a bug),
  the verdict block matches verdict() recomputed from the ledger, and the
  b77 pre-flight ran on the CHRONOLOGICAL order (W4 oldest -> W1 newest),
  never the label order;
- verdict()'s decision rule on synthetic ledgers: REPLICATED needs the
  beat in EVERY window; None (0 trades) and ties never beat; the cached
  leg never counts;
- the registry rows in b62_strategy_lab.json carry the five-leg numbers.
"""
import json
import os
import sys
import datetime
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68o_weekly_lab as wk          # noqa: E402
from scripts import b68o_confirm_weekly as r15     # noqa: E402

LAB = os.path.join(ROOT, "data", "backtest", "b68o_weekly_lab.json")
CONFIRM = os.path.join(ROOT, "data", "backtest", "b68o_weekly_confirm.json")
R14 = os.path.join(ROOT, "data", "backtest", "b68n4_fourth_draw.json")
REGISTRY = os.path.join(ROOT, "data", "backtest", "b62_strategy_lab.json")

UTC = datetime.timezone.utc


def _load(path):
    with open(path) as f:
        return json.load(f)


def bar(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c,
            "tick_volume": 100}


def synth_weeks():
    """Two synthetic trading weeks of M15 bars: week 1 ranges [100, 200],
    week 2 starts flat so we can inject a close-through break on demand.
    Bars are placed Tue-Fri 02:00-23:45 UTC to avoid the DAY_SHIFT edge."""
    rows = []
    t0 = int(datetime.datetime(2025, 3, 4, 2, 0, tzinfo=UTC).timestamp())
    for k in range(95 * 4):                # ~4 days of bars, week 1
        t = t0 + k * 900
        rows.append(bar(t, 150, 200, 100, 150))
    t1 = int(datetime.datetime(2025, 3, 11, 2, 0, tzinfo=UTC).timestamp())
    for k in range(95 * 4):                # week 2 (ISO 2025-11)
        t = t1 + k * 900
        rows.append(bar(t, 150, 151, 149, 150))
    return rows


class TestTradingWeekSemantics(unittest.TestCase):
    def test_day_shift_moves_midnight_bars_back(self):
        # Mon 00:30 UTC shifts to Sunday -> previous ISO week
        mon_0030 = int(datetime.datetime(2025, 3, 10, 0, 30,
                                         tzinfo=UTC).timestamp())
        self.assertEqual(wk.trading_day(mon_0030), datetime.date(2025, 3, 9))
        self.assertEqual(wk.trading_week(mon_0030), (2025, 10))

    def test_day_bar_uses_its_own_week(self):
        tue_02 = int(datetime.datetime(2025, 3, 11, 2, 0,
                                       tzinfo=UTC).timestamp())
        self.assertEqual(wk.trading_week(tue_02), (2025, 11))


class TestWeekLevels(unittest.TestCase):
    def test_level_from_previous_week_only(self):
        rows = synth_weeks()
        levels = wk.build_week_levels(rows)
        self.assertIn((2025, 11), levels)
        self.assertEqual(levels[(2025, 11)], (200, 100))
        # the dataset's FIRST week has no level (nothing to carry over)
        self.assertNotIn((2025, 10), levels)

    def test_stub_week_never_becomes_a_level(self):
        rows = synth_weeks()
        w1 = [r for r in rows if wk.trading_week(r["time"]) == (2025, 10)]
        w2 = [r for r in rows if wk.trading_week(r["time"]) == (2025, 11)]
        # chop week 1 down to a holiday stub: level for week 2 must vanish
        levels = wk.build_week_levels(w1[:10] + w2)
        self.assertNotIn((2025, 11), levels)

    def test_rebind_rebuilds_levels_never_stale(self):
        saved = (wk.M15, wk.IDX, wk.LEVELS)
        try:
            wk.rebind(synth_weeks())
            self.assertEqual(wk.LEVELS[(2025, 11)], (200, 100))
            wk.rebind(saved[0])
            self.assertEqual(wk.LEVELS, saved[2])
        finally:
            wk.M15, wk.IDX, wk.LEVELS = saved


class TestGeometry(unittest.TestCase):
    def setUp(self):
        self.rows = synth_weeks()
        self.levels = wk.build_week_levels(self.rows)

    def _inject(self, closes, at_from_end=3):
        """Overwrite the last few bars' closes in week 2 to build a break;
        the entry bar's OPEN follows the signal close (as it does in real
        data — a gap back inside the range would make risk negative)."""
        rows = [dict(r) for r in self.rows]
        n = len(rows)
        for k, c in enumerate(closes):
            rows[n - at_from_end + k]["close"] = c
        rows[n - 1]["open"] = closes[-1]
        return rows

    def test_close_through_high_buys_next_open(self):
        # prior bar below 200, signal bar CLOSES above 200 -> BUY at next open
        rows = self._inject([199.0, 201.0])
        i = len(rows) - 1
        s = wk.pwh_break_at(rows, None, self.levels, i, 1.0)
        self.assertIsNotNone(s)
        self.assertEqual(s["side"], "BUY")
        self.assertEqual(s["entry"], rows[i]["open"])
        self.assertLess(s["sl"], 200)          # SL beyond the broken level
        risk = s["entry"] - s["sl"]
        self.assertAlmostEqual(s["tp"], s["entry"] + 2 * risk)
        self.assertEqual(s["grade"], "B")

    def test_wick_through_is_not_a_signal(self):
        # high pokes above 200 but the bar CLOSES back below -> no signal
        rows = [dict(r) for r in self.rows]
        rows[-2]["close"] = 199.0
        rows[-2]["high"] = 205.0
        s = wk.pwh_break_at(rows, None, self.levels, len(rows) - 1, 1.0)
        self.assertIsNone(s)

    def test_prior_bar_already_above_does_not_re_fire(self):
        rows = self._inject([202.0, 203.0])   # both closes above PWH
        s = wk.pwh_break_at(rows, None, self.levels, len(rows) - 1, 1.0)
        self.assertIsNone(s)

    def test_low_break_sells_mirrored(self):
        rows = self._inject([101.0, 99.0])
        s = wk.pwh_break_at(rows, None, self.levels, len(rows) - 1, 1.0)
        self.assertIsNotNone(s)
        self.assertEqual(s["side"], "SELL")
        self.assertGreater(s["sl"], 100)
        risk = s["sl"] - s["entry"]
        self.assertAlmostEqual(s["tp"], s["entry"] - 2 * risk)

    def test_no_level_no_signal(self):
        rows = self._inject([199.0, 201.0])
        s = wk.pwh_break_at(rows, None, {}, len(rows) - 1, 1.0)
        self.assertIsNone(s)


class TestCachedLabLedger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = _load(LAB)

    def test_harness_contract_both_arms(self):
        for arm in ("pwh_break_t50", "pwh_break_w10"):
            row = self.led[arm]
            for mode in ("plain", "ladder", "ladder_ts"):
                self.assertIn(mode, row)
                # the REAL b71 harness column names (lab_harness.summary)
                for col in ("trades", "exp_R", "net_R", "maxDD_R",
                            "mean_hold_bars", "p95_hold_bars",
                            "max_hold_bars", "holds_over_time_exit"):
                    self.assertIn(col, row[mode], f"{arm}/{mode}/{col}")

    def test_no_honesty_complaints(self):
        self.assertEqual(self.led["_honesty_complaints"], [])

    def test_cached_leg_is_one_sided_disclosure(self):
        # The round's disclosure fact: on the cached (recent, bullish)
        # regime EVERY weekly break is a HIGH break — 24 BUY, 0 SELL.
        # Anyone quoting the cached exp_R must know it is one-sided.
        p = self.led["_probe"]
        self.assertEqual(p["signals"], 24)
        self.assertEqual(p["buy"], 24)
        self.assertEqual(p["sell"], 0)
        self.assertGreaterEqual(p["weeks_with_level"], 5)

    def test_time_stop_shipped(self):
        self.assertGreaterEqual(self.led["_time_stop_bars"], 1)


@unittest.skipUnless(os.path.exists(CONFIRM),
                     "five-leg confirm ledger not shipped yet")
class TestConfirmLedger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = _load(CONFIRM)
        cls.r14 = _load(R14)

    def test_independent_legs_have_zero_overlap(self):
        for w in r15.WINDOWS:
            self.assertEqual(self.led[w]["_overlap_with_cached"], 0, w)
            self.assertEqual(self.led[w]["_bars"], 6000, w)

    def test_funnel_continuity_with_round14(self):
        # same bars, same harness: the funnel ladder_ts rows on W1..W4
        # must reproduce round 14's shipped ledger exactly.
        for w in r15.WINDOWS:
            a = self.led[w]["CURRENT_FUNNEL"]["ladder_ts"]
            b = self.r14[w]["CURRENT_FUNNEL"]["ladder_ts"]
            self.assertEqual(a["exp_R"], b["exp_R"], w)
            self.assertEqual(a["trades"], b["trades"], w)

    def test_verdict_matches_recomputation(self):
        v = r15.verdict(self.led)
        for k, val in self.led["_verdict"].items():
            self.assertEqual(v[k], val, k)

    def test_b77_preflight_chronological_not_label_order(self):
        pf = self.led["_b77_preflight"]
        # labels are newest-first; time order must be W4 -> W1
        self.assertEqual(pf["_chrono_order_oldest_first"],
                         ["W4", "W3", "W2", "W1"])
        for arm in ("pwh_break_t50", "pwh_break_w10"):
            self.assertIn(arm, pf)
            self.assertIn(pf[arm]["verdict"],
                          ("REGIME_GIFTED", "DECAYING", "MIXED",
                           "INSUFFICIENT"))

    def test_harness_contract_every_leg(self):
        for leg in r15.LEGS:
            for arm in r15.ARMS:
                row = self.led[leg][arm]
                for mode in ("plain", "ladder", "ladder_ts"):
                    self.assertIn("exp_R", row[mode], f"{leg}/{arm}/{mode}")


class TestVerdictRule(unittest.TestCase):
    @staticmethod
    def _led(vals):
        """vals: {window: {arm: exp_R}} with funnel under CURRENT_FUNNEL."""
        led = {}
        for w, m in vals.items():
            led[w] = {"CURRENT_FUNNEL":
                      {"ladder_ts": {"exp_R": m["f"], "trades": 100,
                                     "dd_R": -5.0}}}
            for arm in ("pwh_break_t50", "pwh_break_w10"):
                led[w][arm] = {"ladder_ts": {"exp_R": m.get(arm),
                                             "trades": 10, "dd_R": -2.0}}
        return led

    def test_all_windows_beat_is_replicated(self):
        led = self._led({"W1": {"f": 0.5, "pwh_break_w10": 0.6},
                         "W2": {"f": 0.5, "pwh_break_w10": 0.6},
                         "W3": {"f": 0.5, "pwh_break_w10": 0.6},
                         "W4": {"f": 0.5, "pwh_break_w10": 0.6}})
        v = r15.verdict(led)
        self.assertTrue(v["replicated_in_all"]["pwh_break_w10"])

    def test_one_window_loss_is_not_replicated(self):
        led = self._led({"W1": {"f": 0.5, "pwh_break_w10": 0.6},
                         "W2": {"f": 0.5, "pwh_break_w10": 0.6},
                         "W3": {"f": 0.5, "pwh_break_w10": 0.6},
                         "W4": {"f": 0.55, "pwh_break_w10": 0.5}})
        v = r15.verdict(led)
        self.assertFalse(v["replicated_in_all"]["pwh_break_w10"])

    def test_none_and_ties_never_beat(self):
        led = self._led({"W1": {"f": 0.5, "pwh_break_w10": None},
                         "W2": {"f": 0.5, "pwh_break_w10": 0.5},
                         "W3": {"f": 0.5, "pwh_break_w10": 0.6},
                         "W4": {"f": 0.5, "pwh_break_w10": 0.6}})
        v = r15.verdict(led)
        self.assertFalse(v["W1"]["pwh_break_w10"]["beats_funnel"])
        self.assertFalse(v["W2"]["pwh_break_w10"]["beats_funnel"])
        self.assertFalse(v["replicated_in_all"]["pwh_break_w10"])

    def test_cached_leg_never_counts(self):
        led = self._led({"W1": {"f": 0.5, "pwh_break_w10": 0.6},
                         "W2": {"f": 0.5, "pwh_break_w10": 0.6},
                         "W3": {"f": 0.5, "pwh_break_w10": 0.6},
                         "W4": {"f": 0.5, "pwh_break_w10": 0.6}})
        led["cached"] = {"CURRENT_FUNNEL":
                         {"ladder_ts": {"exp_R": 0.854, "trades": 300}}}
        v = r15.verdict(led)
        self.assertNotIn("cached", v)


@unittest.skipUnless(os.path.exists(CONFIRM),
                     "five-leg confirm ledger not shipped yet")
class TestRegistry(unittest.TestCase):
    def test_round15_rows_shipped(self):
        reg = _load(REGISTRY)
        rows = {r.get("name"): r for r in reg
                if r.get("name") in ("pwh_break_t50", "pwh_break_w10")}
        self.assertEqual(len(rows), 2)
        for name, row in rows.items():
            self.assertEqual(row["round"], 15)
            for leg in r15.LEGS:
                self.assertIn(leg, row["windows"], name)
            # the row states the wiring discipline
            self.assertIn("not wired",
                          json.dumps(row).lower())


if __name__ == "__main__":
    unittest.main()
