"""b68 round 16 (b68p) — PDH breakout GATED on weekly RUNWAY.

Round 15 screened the weekly level as GEOMETRY; this round measures it as an
ORACLE: does a previous-day breakout have room to run inside its trading
week (entry >= room*ATR from the previous week's extreme in trade
direction)? Geometry is round 4's pdh_break_w10 UNCHANGED (b75: the day
break is the fresh trigger and carries the stop; the weekly level is
zero-lag background state).

Pinned OFFLINE from synthetic datasets (the runway predicate, the pure
intersection, the bind discipline) and from the SHIPPED ledgers
(data/backtest/b68p_runway_lab.json + b68p_runway_confirm.json):
- runway_at: directional room, BUY checks PWH, SELL checks PWL, None when
  there is no signal or no weekly level (never a fake False);
- gated/complement are a PURE INTERSECTION of the same pdh signal — the
  gate can only REMOVE trades, never invent or reshape one (b72 rule 1);
- the shipped confirm ledger: every independent leg has ZERO overlap with
  the cached span (b76), the funnel rows reproduce round 14's shipped
  ledger exactly on W1..W4 (drift is a bug), every arm row carries the
  b78 BUY/SELL mix and buy+sell == trades, the verdict block matches
  verdict() recomputed from the ledger, and the b77 pre-flight ran on the
  CHRONOLOGICAL order (W4 oldest -> W1 newest);
- THE ROUND'S OWN FINDINGS, pinned so they cannot be quietly re-quoted:
  the gate's selection ordering (runway > no_runway) holds on exactly ONE
  of four independent windows — the same sign-flip that killed round 9's
  champion — and pdh_runway beats the funnel on 2 of 4 windows (fails the
  b74 all-windows rule);
- the registry rows in b62_strategy_lab.json carry the five-leg numbers.
"""
import json
import os
import sys
import datetime
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68p_runway_lab as rp          # noqa: E402
from scripts import b68p_confirm_runway as r16     # noqa: E402
from scripts import b68e_pdh_lab as pl             # noqa: E402
from scripts import b68o_weekly_lab as wk          # noqa: E402

LAB = os.path.join(ROOT, "data", "backtest", "b68p_runway_lab.json")
CONFIRM = os.path.join(ROOT, "data", "backtest", "b68p_runway_confirm.json")
R14 = os.path.join(ROOT, "data", "backtest", "b68n4_fourth_draw.json")
REGISTRY = os.path.join(ROOT, "data", "backtest", "b62_strategy_lab.json")

UTC = datetime.timezone.utc


def _load(path):
    with open(path) as f:
        return json.load(f)


def bar(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c,
            "tick_volume": 100}


def synth_leg():
    """One synthetic week with a previous-week level [100, 200], then a
    close-confirmed PDH-style break inside a flat day. Built so the pdh
    arm fires exactly once, at the last bar, with the entry known."""
    rows = []
    # previous week: Mon..Thu 02:00 UTC, range [100, 200]
    t0 = int(datetime.datetime(2025, 3, 3, 2, 0, tzinfo=UTC).timestamp())
    for k in range(95 * 4):
        rows.append(bar(t0 + k * 900, 150, 200, 100, 150))
    # current week: a quiet day inside the week's range, then a day whose
    # prior day's high is 160 — the break bar closes above it.
    t1 = int(datetime.datetime(2025, 3, 10, 2, 0, tzinfo=UTC).timestamp())
    for k in range(95):                       # day 1: range [140,160]
        rows.append(bar(t1 + k * 900, 150, 160, 140, 150))
    t2 = int(datetime.datetime(2025, 3, 11, 2, 0, tzinfo=UTC).timestamp())
    for k in range(94):                       # day 2: still inside
        rows.append(bar(t2 + k * 900, 150, 160, 140, 150))
    # signal bar: closes ABOVE 160 (prior close 150 <= 160) -> pdh BUY
    rows.append(bar(t2 + 94 * 900, 155, 165, 154, 162))
    # entry bar: the one we query (i = len-1)
    rows.append(bar(t2 + 95 * 900, 163, 166, 162, 165))
    return rows


class TestRunwayPredicate(unittest.TestCase):
    def setUp(self):
        self.rows = synth_leg()
        rp.bind(self.rows)

    def tearDown(self):
        rp.bind(__import__("json").load(open(rp.CACHED_PATH))["M15"])

    def _sig_i(self):
        for i in range(30, len(self.rows)):
            if pl.pdh_break(i, rp.STOP_ATR):
                return i
        self.fail("synthetic leg produced no pdh signal")

    def test_runway_is_directional_room_to_week_high(self):
        i = self._sig_i()
        s = pl.pdh_break(i, rp.STOP_ATR)
        self.assertEqual(s["side"], "BUY")
        # entry ~163, PWH=200, ATR ~20 -> ~1.85 ATR of room: the 1.0 gate
        # passes, the 2.0 gate fails — the predicate is a real threshold,
        # not an always-true formality.
        self.assertTrue(rp.runway_at(self.rows, i, room=1.0))
        self.assertFalse(rp.runway_at(self.rows, i, room=2.0))

    def test_gate_is_pure_intersection_never_reshapes(self):
        i = self._sig_i()
        raw = pl.pdh_break(i, rp.STOP_ATR)
        gated = rp.gated(i, True, 1.0)
        self.assertEqual(gated, raw)          # same dict fields, unchanged
        # an impossible room requirement: the agree arm vanishes and the
        # complement (what the gate drops) IS the raw signal — the gate can
        # only REMOVE trades, never invent or reshape one (b72 rule 1).
        self.assertIsNone(rp.gated(i, True, 999.0))
        self.assertEqual(rp.complement(i, 999.0), raw)

    def test_no_week_level_is_none_not_false(self):
        i = self._sig_i()
        saved = wk.LEVELS
        try:
            wk.LEVELS = {}
            self.assertIsNone(rp.runway_at(self.rows, i, 1.0))
        finally:
            wk.LEVELS = saved

    def test_no_signal_is_none(self):
        self.assertIsNone(rp.runway_at(self.rows, 30, 1.0))


class TestCachedLabLedger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = _load(LAB)

    def test_harness_contract_every_arm(self):
        for arm in ("pdh_w10_control", "pdh_runway", "pdh_no_runway",
                    "pdh_runway_r20", "pdh_no_runway_r20"):
            row = self.led[arm]
            for mode in ("plain", "ladder", "ladder_ts"):
                self.assertIn(mode, row)
                for col in ("trades", "exp_R", "net_R", "maxDD_R",
                            "mean_hold_bars", "p95_hold_bars",
                            "max_hold_bars", "holds_over_time_exit"):
                    self.assertIn(col, row[mode], f"{arm}/{mode}/{col}")

    def test_no_honesty_complaints(self):
        self.assertEqual(self.led["_honesty_complaints"], [])

    def test_probe_is_anti_vacuous(self):
        # b72 rule 2: the gate must actually split the signals — both arms
        # non-empty on the cached leg, and the split sums with no_week_level
        # back to the raw pdh signal count.
        p = self.led["_probe"]
        self.assertGreater(p["runway_buy"] + p["runway_sell"], 5)
        self.assertGreater(p["no_runway_buy"] + p["no_runway_sell"], 5)
        self.assertEqual(
            p["pdh_signals"],
            p["runway_buy"] + p["runway_sell"] + p["no_runway_buy"]
            + p["no_runway_sell"] + p["no_week_level"])

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
        for w in r16.WINDOWS:
            self.assertEqual(self.led[w]["_overlap_with_cached"], 0, w)
            self.assertEqual(self.led[w]["_bars"], 6000, w)

    def test_funnel_continuity_with_round14(self):
        # same bars, same harness: the funnel ladder_ts rows on W1..W4
        # must reproduce round 14's shipped ledger exactly.
        for w in r16.WINDOWS:
            a = self.led[w]["CURRENT_FUNNEL"]["ladder_ts"]
            b = self.r14[w]["CURRENT_FUNNEL"]["ladder_ts"]
            self.assertEqual(a["exp_R"], b["exp_R"], w)
            self.assertEqual(a["trades"], b["trades"], w)

    def test_b78_mix_ships_on_every_arm_leg(self):
        # b78 (round-15 todo): every shipped leg/arm carries buy+sell facts
        # that sum to the trade count — no exp_R may be quoted blind to the
        # direction mix.
        for leg in r16.LEGS:
            for arm in r16.ARMS[1:]:
                mix = self.led[leg][arm]["_mix"]
                self.assertEqual(mix["buy"] + mix["sell"], mix["trades"],
                                 f"{leg}/{arm}")
                self.assertGreater(mix["buy"] + mix["sell"], 0,
                                   f"{leg}/{arm} has no trades to disclose")

    def test_verdict_matches_recomputation(self):
        v = r16.verdict(self.led)
        for k, val in self.led["_verdict"].items():
            self.assertEqual(v[k], val, k)

    def test_gate_fails_all_windows_rule(self):
        # The round's verdict, pinned: pdh_runway is NOT replicated on all
        # four independent windows (it wins W1/W2, loses W3/W4).
        self.assertFalse(self.led["_verdict"]["replicated_in_all"]["pdh_runway"])
        self.assertFalse(self.led["_verdict"]["replicated_in_all"]["pdh_runway_r20"])

    def test_selection_ordering_flips_across_regimes(self):
        # The round's REAL finding: runway > no_runway holds on exactly ONE
        # of four windows (W1) — the gate's selection SIGN flips between
        # regimes, the same failure mode that killed round 9's champion.
        so = self.led["_verdict"]["selection_ordering"]["r10"]
        self.assertEqual(so["agree_gt_cut_windows"], 1)
        self.assertEqual(so["of"], 4)

    def test_b77_preflight_chronological_not_label_order(self):
        pf = self.led["_b77_preflight"]
        self.assertEqual(pf["_chrono_order_oldest_first"],
                         ["W4", "W3", "W2", "W1"])
        for arm in ("pdh_runway", "pdh_runway_r20", "pdh_no_runway"):
            self.assertIn(arm, pf)
            self.assertIn(pf[arm]["verdict"],
                          ("REGIME_GIFTED", "DECAYING", "MIXED",
                           "INSUFFICIENT"))

    def test_harness_contract_every_leg(self):
        for leg in r16.LEGS:
            for arm in r16.ARMS:
                row = self.led[leg][arm]
                for mode in ("plain", "ladder", "ladder_ts"):
                    self.assertIn("exp_R", row[mode], f"{leg}/{arm}/{mode}")


class TestVerdictRule(unittest.TestCase):
    """Synthetic ledgers pin verdict()'s decision semantics."""

    @staticmethod
    def _leg(f_exp, arm_exp, buy=1, sell=1):
        def row(e):
            return {"ladder_ts": {"exp_R": e, "trades": 10, "maxDD_R": -3.0},
                    "_mix": {"trades": buy + sell, "buy": buy, "sell": sell}}
        return {"CURRENT_FUNNEL": row(f_exp),
                "pdh_w10_control": row(arm_exp),
                "pdh_runway": row(arm_exp),
                "pdh_no_runway": row(arm_exp),
                "pdh_runway_r20": row(arm_exp),
                "pdh_no_runway_r20": row(arm_exp),
                "lane_funnel_then_runway": row(arm_exp)}

    def test_replication_needs_every_window(self):
        led = {"W1": self._leg(0.5, 0.6), "W2": self._leg(0.5, 0.6),
               "W3": self._leg(0.5, 0.6), "W4": self._leg(0.5, 0.49),
               "cached": self._leg(0.5, 0.6)}
        v = r16.verdict(led)
        self.assertFalse(v["replicated_in_all"]["pdh_runway"])

    def test_none_and_ties_never_beat(self):
        led = {"W1": self._leg(0.5, None), "W2": self._leg(0.5, 0.5),
               "W3": self._leg(0.5, 0.6), "W4": self._leg(0.5, 0.6),
               "cached": self._leg(0.5, 0.6)}
        v = r16.verdict(led)
        self.assertFalse(v["W1"]["pdh_runway"]["beats_funnel"])
        self.assertFalse(v["W2"]["pdh_runway"]["beats_funnel"])
        self.assertFalse(v["replicated_in_all"]["pdh_runway"])

    def test_full_sweep_replicates(self):
        led = {w: self._leg(0.5, 0.6) for w in ("W1", "W2", "W3", "W4")}
        led["cached"] = self._leg(0.5, 0.6)
        v = r16.verdict(led)
        self.assertTrue(v["replicated_in_all"]["pdh_runway"])
        self.assertEqual(v["selection_ordering"]["r10"]["agree_gt_cut_windows"], 0)


class TestRegistryRows(unittest.TestCase):
    def test_round16_rows_shipped(self):
        rows = {r["name"]: r for r in _load(REGISTRY)}
        for name in ("pdh_runway", "pdh_no_runway"):
            self.assertIn(name, rows)
            r = rows[name]
            self.assertEqual(r["round"], 16)
            for w in ("cached", "W1", "W2", "W3", "W4"):
                self.assertIn(w, r["windows"])
                self.assertIn("buy", r["windows"][w])   # b78 mix in registry
            self.assertIn("NOT WIRED", r["verdict"].upper())
        # the candidate arm carries the explicit rejection; the complement
        # is evidence, not a candidate, so it only owes the NOT-wired fact.
        self.assertIn("REJECTED", rows["pdh_runway"]["verdict"].upper())


if __name__ == "__main__":
    unittest.main()
