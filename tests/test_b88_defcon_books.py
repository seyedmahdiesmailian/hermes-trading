"""b88 (b68 round 20) — DEFCON measured as a FEEDBACK-LOOP book, plus the fix
to the one input defect the measurement exposed.

b87's queue named DEFCON after range-kill, and it is a different animal: every
other live gate reads the MARKET (grade, RR, spread, news, cooldown), DEFCON is
the only one that reads the book's OWN past trades. That makes it the one gate
whose correctness depends on plumbing nobody else depends on — so this round
audited the plumbing before pricing the rule.

Two defects found, both in engines/risk.compute_performance_state, the function
that builds DEFCON's input:

(1) THE DAY-ROLLOVER BLIND CYCLE (FIXED here). The function has two returns.
    The same-day branch sets `recent_closed` (the last 10 deals DEFCON
    classifies); the new-day branch returned a dict WITHOUT that key. So the
    FIRST evaluation cycle of every new UTC day handed DEFCON an empty window
    with loss_streak=0 and daily_pnl=0.0 — compute_insights then returns GREEN
    by construction (total=0 fails RED's `total>=5`, streak 0 fails YELLOW's
    `>=2`, sl_ratio 0 fails `>=0.5`). Not a wrong level: NO level. And it was
    blind exactly on the cycle where "you bled yesterday, do not open today's
    first trade at full size" is worth the most.
    FIX: carry the window through the rollover. STRICTLY tightening — daily_pnl
    is 0.0 on that cycle so RED still cannot fire, and YELLOW only halves risk,
    so no gate gets looser (hard rule respected). `loss_streak` stays reset on
    purpose: it also feeds check_kill_switch and assess_account_policy, and
    carrying it across days would silently redefine the kill switch to
    multi-day streaks. That is a human decision, not a side effect.
    Ledger measures the blast radius: 122 of 259 first-entry-of-day cycles
    (cached+W1..W4) sat at a level the bug invented -- 107 should have been
    YELLOW and 15 RED, i.e. entries taken at FULL risk that the gate, wired
    correctly, would have halved or blocked.

(2) DEALS vs TRADES (MEASURED, NOT CHANGED — a proposal for a human). The
    docstring says "last 10 closed trades"; the code takes the last 10 DEALS
    from a feed that contains opening deals too (entry==0). A round trip is two
    deals, so the window holds ~5 closed trades, and `total>=5` — the threshold
    that makes RED reachable at all — sits exactly on that halving. Changing it
    would TIGHTEN DEFCON globally (level mix goes GREEN 125 -> YELLOW 96 on W1),
    which is a gate change, so it is reported, not applied. (Replay is
    chronological per b77: a trade is folded into the state only once its EXIT
    precedes the entry being evaluated.)

What the book says about the rule itself (b87 template, 5 legs, b71 harness,
b80 gates, b83 reproduce-b80 parity pinned below):
  - It BINDS, unlike range-kill (b86): 6-12 RED and 40-80 YELLOW entries per
    leg out of 99-190 trades.
  - It is NOT redundant with the kill switch: 44 of 45 RED entries sat below
    CONSECUTIVE_LOSSES_LIMIT=4, where the kill switch is silent. DEFCON is the
    earlier trip wire -- the only one that catches sl_dominant-but-not-yet-4
    losing days.
  - It is NOT profitable as a filter: the dropped book earns 0.51-1.23R, above
    the kept book's 0.66-0.76R on 4 of 5 legs. It blocks good trades.
  - It is still the right gate to keep: it fires on losing streaks, and a
    protection whose cost is measured in foregone R is a decision about tail
    risk, not about mean R. Nothing here justifies weakening it (hard rule).
  - No adaptive path touches it: learning.py's changes dict never contains a
    DEFCON key; its triggers are literals in compute_insights.

Read-only lab. No order endpoint, no gate weakened.
"""
import json
import os
import sys
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = os.path.join(ROOT, "data", "backtest", "b88_defcon_books.json")
PARITY = os.path.join(ROOT, "data", "backtest", "b80_gate_parity.json")
LEGS = ("cached", "W1", "W2", "W3", "W4")
LEVELS = ("GREEN", "YELLOW", "RED")


def _load(path):
    with open(path) as f:
        return json.load(f)


def _deals(n_pairs, profit_fn, day_ts):
    """A live-shaped feed: opening deal (entry=0) then closing deal per trade."""
    out = []
    for i in range(n_pairs):
        out.append({"ticket": 2 * i + 1, "entry": 0, "time": day_ts, "profit": 0.0,
                    "comment": "HermesOpen"})
        out.append({"ticket": 2 * i + 2, "entry": 1, "time": day_ts,
                    "profit": profit_fn(i), "comment": "[sl 10.0] xau_plan"})
    return out


class TestRolloverCarriesTheWindow(unittest.TestCase):
    """The fix: DEFCON must not be blind on the first cycle of a new UTC day."""

    def test_new_day_state_still_has_recent_closed(self):
        from engines.risk import compute_performance_state
        now = datetime.now(timezone.utc)
        deals = _deals(5, lambda i: -10.0, now.timestamp())
        prev = {"day": "2020-01-01", "trades_today": 5, "daily_pnl": -50.0,
                "loss_streak": 3, "recent_closed": deals[-10:]}
        state = compute_performance_state(prev, now.date().isoformat(), 5000.0, deals)
        self.assertIn("recent_closed", state)
        self.assertEqual(len(state["recent_closed"]), 10)

    def test_rollover_window_is_the_live_tail_of_the_feed(self):
        # same expression as the same-day branch: no second source of truth
        from engines.risk import compute_performance_state
        deals = _deals(9, lambda i: -1.0, 1_700_000_000)
        rollover = compute_performance_state({"day": "2020-01-01"}, "2026-09-05",
                                             5000.0, deals)
        sameday = compute_performance_state({"day": "2026-09-05"}, "2026-09-05",
                                           5000.0, deals)
        self.assertEqual(rollover["recent_closed"], sameday["recent_closed"])

    def test_empty_feed_stays_empty(self):
        from engines.risk import compute_performance_state
        state = compute_performance_state({"day": "2020-01-01"}, "2026-09-05",
                                          5000.0, [])
        self.assertEqual(state["recent_closed"], [])

    def test_loss_streak_still_resets_on_rollover(self):
        # PINNED ON PURPOSE. Carrying it would redefine check_kill_switch
        # (CONSECUTIVE_LOSSES_LIMIT) as a multi-day streak — a gate change.
        from engines.risk import compute_performance_state
        prev = {"day": "2020-01-01", "loss_streak": 3, "daily_pnl": -99.0}
        state = compute_performance_state(prev, "2026-09-05", 5000.0, [])
        self.assertEqual(state["loss_streak"], 0)
        self.assertEqual(state["daily_pnl"], 0.0)


class TestFixIsStrictlyTightening(unittest.TestCase):
    """Hard rule: never weaken a gate. The fix may only ever ADD caution."""

    def _level(self, state, balance=5000.0):
        from engines.defcon import classify_exits, compute_insights
        return compute_insights(
            loss_streak=int(state.get("loss_streak", 0) or 0),
            daily_pnl=float(state.get("daily_pnl", 0) or 0),
            balance=balance,
            classified=classify_exits(state.get("recent_closed") or []),
        )

    def test_bloody_previous_day_no_longer_reads_green(self):
        from engines.risk import compute_performance_state
        from engines.defcon import classify_exits, compute_insights
        now = datetime.now(timezone.utc)
        deals = _deals(5, lambda i: -10.0, now.timestamp())

        # PRE-FIX behaviour: the new-day dict had no window at all.
        pre_fix = {"day": now.date().isoformat(), "starting_balance": 5000.0,
                   "daily_pnl": 0.0, "loss_streak": 0, "trades_today": 0,
                   "last_closed_ticket": None}
        self.assertEqual(self._level(pre_fix)["defcon"], "GREEN")

        state = compute_performance_state({"day": "2020-01-01"},
                                          now.date().isoformat(), 5000.0, deals)
        self.assertEqual(self._level(state)["defcon"], "YELLOW")

    def test_red_cannot_fire_on_a_rollover_cycle(self):
        # RED needs daily_pnl < 0; the rollover zeroes it, so the fix can never
        # block entries outright — worst case it halves risk (YELLOW).
        from engines.risk import compute_performance_state
        for n, prof in ((9, lambda i: -10.0), (5, lambda i: -1.0)):
            deals = _deals(n, prof, 1_700_000_000)
            state = compute_performance_state({"day": "2020-01-01"}, "2026-09-05",
                                              5000.0, deals)
            self.assertEqual(state["daily_pnl"], 0.0)
            ins = self._level(state)
            self.assertNotEqual(ins["defcon"], "RED")
            self.assertTrue(ins["trade_allowed"])

    def test_risk_override_never_exceeds_full_size(self):
        from engines.risk import compute_performance_state
        deals = _deals(6, lambda i: -10.0, 1_700_000_000)
        state = compute_performance_state({"day": "2020-01-01"}, "2026-09-05",
                                          5000.0, deals)
        ins = self._level(state)
        self.assertTrue(ins["risk_override"] is None or ins["risk_override"] <= 1.0)


class TestLedgerShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest(f"{LEDGER} not built yet")
        cls.led = _load(LEDGER)

    def test_all_legs_and_books_present(self):
        for leg in LEGS:
            L = self.led[leg]
            for book in ("defcon_off", "kept_defcon", "dropped_defcon",
                         "kept_corrected", "dropped_corrected", "blind_cycle_book"):
                self.assertIn(book, L, f"{leg}.{book}")
                for mode in ("plain", "ladder", "ladder_ts"):
                    self.assertIn(mode, L[book])
                    self.assertIsNotNone(L[book][mode]["mean_hold_bars"])

    def test_states_carry_the_input_contract_fields(self):
        for leg in LEGS:
            for s in self.led[leg]["_states"]:
                for key in ("defcon_live", "defcon_corrected", "defcon_pre_fix",
                            "window_deals", "window_exits", "loss_streak",
                            "daily_pnl", "first_entry_of_utc_day",
                            "kill_switch_armed", "trade_allowed_live"):
                    self.assertIn(key, s)

    def test_mix_ships_per_leg(self):
        for leg in LEGS:
            mix = self.led[leg]["defcon_off"]["_mix"]
            self.assertEqual(mix["buy"] + mix["sell"], mix["trades"])
            self.assertGreater(mix["trades"], 0)


class TestIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (os.path.exists(LEDGER) and os.path.exists(PARITY)):
            raise unittest.SkipTest("ledger or b80 parity file missing")
        cls.led = _load(LEDGER)
        cls.par = _load(PARITY)

    def test_defcon_off_row_reproduces_b80(self):
        # b83: the funnel with DEFCON switched off must print b80's gradeB_rr15
        # column exactly. A drift here means this round measured a different
        # system than the one in production.
        for leg in LEGS:
            a = self.led[leg]["defcon_off"]["ladder_ts"]
            b = self.par["legs"][leg]["gradeB_rr15"]
            self.assertEqual((a["trades"], a["exp_R"], a["net_R"]),
                             (b["trades"], b["exp_R"], b["net_R"]),
                             f"{leg}: b88 defcon_off diverged from b80")
        self.assertTrue(self.led["_verdict"]["parity_all_match"])

    def test_level_mix_partitions_the_states(self):
        # GREEN+YELLOW+RED per leg must equal the trade count the replay saw.
        # The kept/dropped BOOKS deliberately do NOT sum to that: each is a
        # fresh funnel re-simulation with entries removed, so the path changes
        # (a blocked entry frees a slot for a later signal). Partitioning the
        # states list is the honest invariant; partitioning re-simulated books
        # would be a bug to assert.
        for leg in LEGS:
            L = self.led[leg]
            self.assertEqual(sum(L["_defcon_level_mix"].values()),
                             L["_book_trades"], leg)
            self.assertEqual(sum(L["_defcon_corrected_mix"].values()),
                             L["_book_trades"], leg)
            self.assertEqual(len(L["_states"]), L["_book_trades"], leg)

    def test_ledger_built_against_the_fixed_code_path(self):
        # The rollover fix changes defcon_live, so a ledger produced by the
        # pre-fix replay must not be allowed to pass as current.
        self.assertTrue(self.led.get("_risk_code_sha"),
                        "ledger missing _risk_code_sha stamp")
        import hashlib
        with open(os.path.join(ROOT, "engines", "risk.py"), "rb") as f:
            now = hashlib.sha256(f.read()).hexdigest()[:12]
        self.assertEqual(self.led["_risk_code_sha"], now,
                         "engines/risk.py changed after the ledger was built — "
                         "re-run scripts/b88_defcon_books.py")


class TestDefconBinds(unittest.TestCase):
    """The b86 contrast: range-kill was a no-op at its live threshold. DEFCON
    is not — it fires on every leg, so its cost is real and must be priced."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest(f"{LEDGER} not built yet")
        cls.led = _load(LEDGER)

    def test_fires_on_every_leg(self):
        for leg in LEGS:
            L = self.led[leg]
            self.assertGreater(L["_red_entries"], 0, leg)
            self.assertGreater(L["_yellow_entries"], 0, leg)

    def test_dropped_book_is_positive_r(self):
        # The gate blocks trades that would have made money. Recorded, not
        # acted on: weakening DEFCON is a hard-rule violation.
        for leg in LEGS:
            exp_R = self.led[leg]["dropped_defcon"]["ladder_ts"]["exp_R"]
            self.assertGreater(exp_R, 0.0, leg)

    def test_not_redundant_with_the_kill_switch(self):
        # DEFCON's RED needs streak>=2 while the kill switch arms at 4, so most
        # RED entries sit where the kill switch is silent. If this ever inverts,
        # DEFCON is dead weight and should be re-proposed for removal.
        total_red = sum(self.led[leg]["_red_entries"] for leg in LEGS)
        covered = sum(self.led[leg]["_red_blocked_behind_kill_switch"] for leg in LEGS)
        self.assertGreater(total_red, 0)
        self.assertLess(covered, total_red)


class TestWindowShape(unittest.TestCase):
    """Defect (2): the live window is DEALS, the docstring says TRADES."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest(f"{LEDGER} not built yet")
        cls.led = _load(LEDGER)

    def test_window_is_half_closed_trades(self):
        for leg in LEGS:
            L = self.led[leg]
            self.assertEqual(L["_window_deals_median"], 10, leg)
            self.assertEqual(L["_window_exits_median"], 5, leg)

    def test_corrected_window_is_tighter_not_looser(self):
        # Removing opening deals can only ADD caution here (more RED/YELLOW),
        # which is why it is a proposal rather than a silent fix.
        for leg in LEGS:
            L = self.led[leg]
            self.assertGreater(L["_corrected_stricter_entries"],
                               L["_corrected_looser_entries"], leg)

    def test_red_threshold_sits_on_the_halving(self):
        # RED needs total>=5 and the live median window is exactly 5 exits: the
        # rule is reachable only because of how the feed is sliced.
        for leg in LEGS:
            self.assertGreaterEqual(self.led[leg]["_window_exits_median"], 5)


class TestBlastRadius(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LEDGER):
            raise unittest.SkipTest(f"{LEDGER} not built yet")
        cls.led = _load(LEDGER)

    def test_blind_cycle_affected_entries_on_every_leg(self):
        for leg in LEGS:
            self.assertGreater(self.led[leg]["_blind_cycle_entries"], 0, leg)

    def test_blind_cycle_was_always_a_downgrade_to_green(self):
        # The bug could only invent caution-free cycles, never block a trade:
        # pre-fix GREEN is the floor of the ladder.
        for leg in LEGS:
            for s in self.led[leg]["_states"]:
                if s["defcon_pre_fix"] != s["defcon_live"]:
                    self.assertEqual(s["defcon_pre_fix"], "GREEN", leg)
                    self.assertTrue(s["first_entry_of_utc_day"], leg)

    def test_verdict_totals_present(self):
        v = self.led["_verdict"]
        for key in ("binding", "dropped_book", "kept_vs_off",
                    "redundancy_vs_kill_switch", "rollover_blind_cycle",
                    "window_shape", "adaptive_reach", "mix"):
            self.assertIn(key, v)
        self.assertFalse(v["adaptive_reach"]["learning_can_move_defcon"])


if __name__ == "__main__":
    unittest.main()
