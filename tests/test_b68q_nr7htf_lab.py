"""b68 round 17 (b68q) — NR7 compression breakout GATED on the H4 trend state.

The last unmeasured pairing of the loop's two strongest survivors: nr7
geometry (round 5 — the only arm whose additive lane beat the funnel's own
per-trade R) x the H4 EMA trend-state oracle (round 12 — the only gate that
lifted its control on BOTH independent clean windows). Geometry is
nr7_break_w10 UNCHANGED (b75: the squeeze break IS the fresh trigger; the H4
state is zero-lag background), oracle imported verbatim from
b68m_htf_pdh_lab so the two rounds cannot drift.

Pinned OFFLINE from synthetic datasets (the gate predicate, the pure
intersection, the no-lookahead convention, the silent-state exclusion) and
from the SHIPPED ledgers (data/backtest/b68q_nr7htf_lab.json +
b68q_nr7htf_confirm.json):
- gated/complement are a PURE INTERSECTION of the same nr7 signal — the gate
  can only REMOVE trades, never invent or reshape one (b72 rule 1);
- trend_state reads only H4 bars FULLY CLOSED before the entry bar opens;
- the shipped confirm ledger: every independent leg has ZERO overlap with
  the cached span (b76), the funnel rows reproduce round 16's shipped
  ledger exactly on W1..W4 (drift is a bug), every arm row carries the b78
  BUY/SELL mix and buy+sell == trades, the verdict block matches verdict()
  recomputed from the ledger, and the b77 pre-flight ran on the
  CHRONOLOGICAL order (W4 oldest -> W1 newest);
- the registry rows in b62_strategy_lab.json carry the five-leg numbers.
"""
import json
import os
import sys
import datetime
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts import b68q_nr7htf_lab as q          # noqa: E402
from scripts import b68q_confirm_nr7htf as r17    # noqa: E402
from scripts import b68f_nr7_lab as nf            # noqa: E402
from scripts import b68m_htf_pdh_lab as mm        # noqa: E402

LAB = os.path.join(ROOT, "data", "backtest", "b68q_nr7htf_lab.json")
CONFIRM = os.path.join(ROOT, "data", "backtest", "b68q_nr7htf_confirm.json")
R16 = os.path.join(ROOT, "data", "backtest", "b68p_runway_confirm.json")
REGISTRY = os.path.join(ROOT, "data", "backtest", "b62_strategy_lab.json")

UTC = datetime.timezone.utc


def _load(path):
    with open(path) as f:
        return json.load(f)


def bar(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c,
            "tick_volume": 100}


def synth_m15_buy_break():
    """Wide-range bars, then an NR7 squeeze bar, then a close-confirmed
    break of its high. The queried entry bar i is the LAST bar."""
    t0 = int(datetime.datetime(2025, 3, 3, 2, 0, tzinfo=UTC).timestamp())
    rows = []
    k = 0
    for _ in range(40):                       # wide bars, range 10
        rows.append(bar(t0 + k * 900, 105, 110, 100, 105))
        k += 1
    # NR7 squeeze bar (range 2, narrowest of the last 7)
    rows.append(bar(t0 + k * 900, 105, 106, 104, 105))
    j = len(rows) - 1
    k += 1
    rows.append(bar(t0 + k * 900, 105, 106, 104, 105))   # still inside
    k += 1
    rows.append(bar(t0 + k * 900, 105, 108, 104, 108))   # CLOSES above 106
    k += 1
    rows.append(bar(t0 + k * 900, 108.5, 109, 108, 108.8))  # entry bar i
    return rows, j


def synth_h4(rising=True, n=80, span=4 * 3600, base=100, step=0.5):
    """A clean monotonic HTF stream -> a stable BUY (or SELL) EMA50 state."""
    t0 = int(datetime.datetime(2025, 1, 1, 0, 0, tzinfo=UTC).timestamp())
    rows = []
    for i in range(n):
        c = base + step * i if rising else base - step * i
        rows.append(bar(t0 + i * span, c, c + 0.2, c - 0.2, c))
    return rows


class TestGatePredicate(unittest.TestCase):
    """Synthetic pins for the pure-intersection + no-lookahead contract."""

    def setUp(self):
        self.rows, self.j = synth_m15_buy_break()
        self.h4_up = synth_h4(rising=True)
        self.h4_dn = synth_h4(rising=False)

    def tearDown(self):
        data = json.load(open(q.CACHED_PATH))
        q.bind(data["M15"], data["H1"], data["H4"])

    def _entry_i(self):
        for i in range(30, len(self.rows)):
            if nf.nr7_break(i, wide=True):
                return i
        self.fail("synthetic leg produced no nr7 signal")

    def test_agree_keeps_raw_signal_unchanged(self):
        prep = q.bind(self.rows, None, self.h4_up)
        i = self._entry_i()
        raw = nf.nr7_break(i, wide=True)
        self.assertEqual(raw["side"], "BUY")
        self.assertEqual(q.gated(i, prep, "agree"), raw)   # same dict
        self.assertIsNone(q.gated(i, prep, "dis"))

    def test_disagree_flips_the_subset(self):
        prep = q.bind(self.rows, None, self.h4_dn)
        i = self._entry_i()
        raw = nf.nr7_break(i, wide=True)
        self.assertIsNone(q.gated(i, prep, "agree"))
        self.assertEqual(q.gated(i, prep, "dis"), raw)

    def test_silent_state_excluded_from_both_arms(self):
        # fewer than 56 H4 bars -> trend_state is None -> neither arm keeps
        # the signal (it is counted as `silent` in the probe, never as an
        # agree — an uninformed gate must not masquerade as a passing one).
        prep = q.bind(self.rows, None, synth_h4(n=10))
        i = self._entry_i()
        self.assertIsNone(q.gated(i, prep, "agree"))
        self.assertIsNone(q.gated(i, prep, "dis"))

    def test_no_lookahead_future_htf_bars_cannot_change_state(self):
        prep = q.bind(self.rows, None, self.h4_up)
        i = self._entry_i()
        side_before, _ = mm.trend_state(prep, self.rows[i]["time"])
        # poison every H4 bar that CLOSES after the entry bar opens
        cut = self.rows[i]["time"] - 4 * 3600
        poisoned = [r for r in self.h4_up if int(r["time"]) <= cut] + \
                   [bar(t, 9999, 9999, 9999, 9999)
                    for t, *_ in [(int(r["time"]),)
                                  for r in self.h4_up
                                  if int(r["time"]) > cut]]
        prep2 = mm._htf_prep(poisoned, 4 * 3600)
        side_after, _ = mm.trend_state(prep2, self.rows[i]["time"])
        self.assertEqual(side_before, side_after)

    def test_gate_can_only_remove_never_reshape(self):
        prep = q.bind(self.rows, None, self.h4_up)
        for i in range(30, len(self.rows)):
            raw = nf.nr7_break(i, wide=True)
            if raw is None:
                self.assertIsNone(q.gated(i, prep, "agree"))
                self.assertIsNone(q.gated(i, prep, "dis"))
            else:
                g = q.gated(i, prep, "agree")
                self.assertIn(g, (None, raw))


class TestCachedLabLedger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = _load(LAB)

    def test_harness_contract_every_arm(self):
        for arm in ("nr7_w10_control", "nr7_h4t_agree", "nr7_h4t_disagree"):
            row = self.led[arm]
            for mode in ("plain", "ladder", "ladder_ts"):
                self.assertIn(mode, row)
                for col in ("trades", "exp_R", "net_R", "maxDD_R",
                            "mean_hold_bars", "p95_hold_bars",
                            "max_hold_bars", "holds_over_time_exit"):
                    self.assertIn(col, row[mode], f"{arm}/{mode}/{col}")

    def test_no_honesty_complaints(self):
        self.assertEqual(self.led["_honesty_complaints"], [])

    def test_probe_is_anti_vacuous_and_partitions(self):
        # b72 rule 2: both gated arms non-empty, and agree+disagree+silent
        # == the raw nr7 signal count (an exact partition — no signal may
        # vanish uncounted).
        p = self.led["_probe"]
        self.assertGreater(p["agree"], 20)
        self.assertGreater(p["disagree"], 20)
        self.assertEqual(p["nr7_signals"],
                         p["agree"] + p["disagree"] + p["silent"])

    def test_control_reproduces_round5_cached_number(self):
        # b72 rule 3: the ungated ingredient must reproduce round 5's
        # shipped cached ladder number (0.598, n=218) — same bars, same
        # harness; drift is a bug.
        row = self.led["nr7_w10_control"]["ladder"]
        self.assertEqual(row["exp_R"], 0.598)
        self.assertEqual(row["trades"], 218)

    def test_stretch_probe_is_flat_by_construction(self):
        # Pure intersection: the gate cannot move the entry, so control and
        # gated means must be close (a big delta = binding bug, not geometry).
        sp = self.led["_stretch_probe"]
        self.assertIsNotNone(sp["control"]["mean_stretch_atr"])
        self.assertLess(
            abs(sp["gated"]["mean_stretch_atr"]
                - sp["control"]["mean_stretch_atr"]), 0.5)

    def test_time_stop_shipped(self):
        self.assertGreaterEqual(self.led["_time_stop_bars"], 1)


@unittest.skipUnless(os.path.exists(CONFIRM),
                     "five-leg confirm ledger not shipped yet")
class TestConfirmLedger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = _load(CONFIRM)
        cls.r16 = _load(R16)

    def test_independent_legs_have_zero_overlap(self):
        for w in r17.WINDOWS:
            self.assertEqual(self.led[w]["_overlap_with_cached"], 0, w)
            self.assertEqual(self.led[w]["_bars"], 6000, w)

    def test_funnel_continuity_with_round16(self):
        # same bars, same harness: the funnel ladder_ts rows on W1..W4
        # must reproduce round 16's shipped ledger exactly.
        for w in r17.WINDOWS:
            a = self.led[w]["CURRENT_FUNNEL"]["ladder_ts"]
            b = self.r16[w]["CURRENT_FUNNEL"]["ladder_ts"]
            self.assertEqual(a["exp_R"], b["exp_R"], w)
            self.assertEqual(a["trades"], b["trades"], w)

    def test_b78_mix_ships_on_every_arm_leg(self):
        for leg in r17.LEGS:
            for arm in r17.ARMS[1:]:
                mix = self.led[leg][arm]["_mix"]
                self.assertEqual(mix["buy"] + mix["sell"], mix["trades"],
                                 f"{leg}/{arm}")
                self.assertGreater(mix["buy"] + mix["sell"], 0,
                                   f"{leg}/{arm} has no trades to disclose")

    def test_probe_partitions_on_every_leg(self):
        for leg in r17.LEGS:
            p = self.led[leg]["_probe"]
            self.assertEqual(p["nr7_signals"],
                             p["agree"] + p["disagree"] + p["silent"], leg)

    def test_verdict_matches_recomputation(self):
        v = r17.verdict(self.led)
        for k, val in self.led["_verdict"].items():
            self.assertEqual(v[k], val, k)

    def test_b77_preflight_chronological_not_label_order(self):
        pf = self.led["_b77_preflight"]
        self.assertEqual(pf["_chrono_order_oldest_first"],
                         ["W4", "W3", "W2", "W1"])
        for arm in ("nr7_h4t_agree", "nr7_h4t_disagree"):
            self.assertIn(arm, pf)
            self.assertIn(pf[arm]["verdict"],
                          ("REGIME_GIFTED", "DECAYING", "MIXED",
                           "INSUFFICIENT"))

    def test_harness_contract_every_leg(self):
        for leg in r17.LEGS:
            for arm in r17.ARMS:
                row = self.led[leg][arm]
                for mode in ("plain", "ladder", "ladder_ts"):
                    self.assertIn("exp_R", row[mode], f"{leg}/{arm}/{mode}")


class TestVerdictRule(unittest.TestCase):
    """Synthetic ledgers pin verdict()'s decision semantics."""

    @staticmethod
    def _leg(f_exp, agree_exp, cut_exp=None):
        def row(e, buy=1, sell=1):
            return {"ladder_ts": {"exp_R": e, "trades": 10, "maxDD_R": -3.0},
                    "_mix": {"trades": buy + sell, "buy": buy, "sell": sell}}
        return {"CURRENT_FUNNEL": row(f_exp),
                "nr7_w10_control": row(agree_exp),
                "nr7_h4t_agree": row(agree_exp),
                "nr7_h4t_disagree": row(agree_exp if cut_exp is None
                                        else cut_exp),
                "lane_funnel_then_nr7htf": row(agree_exp)}

    def test_replication_needs_every_window(self):
        led = {"W1": self._leg(0.5, 0.6), "W2": self._leg(0.5, 0.6),
               "W3": self._leg(0.5, 0.6), "W4": self._leg(0.5, 0.49),
               "cached": self._leg(0.5, 0.6)}
        v = r17.verdict(led)
        self.assertFalse(v["replicated_in_all"]["nr7_h4t_agree"])

    def test_none_and_ties_never_beat(self):
        led = {"W1": self._leg(0.5, None), "W2": self._leg(0.5, 0.5),
               "W3": self._leg(0.5, 0.6), "W4": self._leg(0.5, 0.6),
               "cached": self._leg(0.5, 0.6)}
        v = r17.verdict(led)
        self.assertFalse(v["W1"]["nr7_h4t_agree"]["beats_funnel"])
        self.assertFalse(v["W2"]["nr7_h4t_agree"]["beats_funnel"])
        self.assertFalse(v["replicated_in_all"]["nr7_h4t_agree"])

    def test_full_sweep_replicates_and_selection_counts(self):
        led = {w: self._leg(0.5, 0.6, cut_exp=0.4)
               for w in ("W1", "W2", "W3", "W4")}
        led["cached"] = self._leg(0.5, 0.6, cut_exp=0.4)
        v = r17.verdict(led)
        self.assertTrue(v["replicated_in_all"]["nr7_h4t_agree"])
        self.assertEqual(v["selection_ordering"]["agree_gt_cut_windows"], 4)


class TestRegistryRows(unittest.TestCase):
    def test_round17_rows_shipped(self):
        rows = {r["name"]: r for r in _load(REGISTRY)}
        for name in ("nr7_h4t_agree", "nr7_h4t_disagree"):
            self.assertIn(name, rows)
            r = rows[name]
            self.assertEqual(r["round"], 17)
            for w in ("cached", "W1", "W2", "W3", "W4"):
                self.assertIn(w, r["windows"])
                self.assertIn("buy", r["windows"][w])   # b78 mix in registry
            self.assertIn("NOT WIRED", r["verdict"].upper())
        # the candidate arm carries the explicit verdict word; the
        # complement is evidence, not a candidate, so it only owes the
        # NOT-wired fact.
        self.assertIn(rows["nr7_h4t_agree"]["verdict"].upper().split()[0],
                      ("REJECTED", "PROMOTED", "CANDIDATE"))


if __name__ == "__main__":
    unittest.main()
