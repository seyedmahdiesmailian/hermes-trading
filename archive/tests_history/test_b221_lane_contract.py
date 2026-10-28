"""b221 — pin the two entry lanes' contract for `positions_unreadable`.

THE DISCREPANCY (found while shipping b219, 2026-10-02):

Both entry lanes build an account policy from `_performance_and_policy`
(hermes_runtime). When the bridge is DARK — the positions reply errors or its
shape is unreadable — b214 makes that read fail CLOSED: it reports
open_positions = MAX_OPEN_POSITIONS and sets the diagnostic flag
`positions_unreadable`. The verdict "do not enter blind" is identical in both
lanes. What differs is WHERE it is delivered:

    plan lane   →  policy['trade_allowed'] = True, regime='normal',
                   open_positions = cap, positions_unreadable = True
                   → the block lands at auto_executor's position-cap gate.

    signal lane →  the same flag makes check_signals build
                   trade_allowed = False directly (a block in the policy
                   itself, before the executor is ever reached).

Neither lane is wrong, and the CONTRACT this file pins:

    An unreadable bridge is refused at the ENTRY GATE, never by the policy
    itself. `positions_unreadable` is the invariant both lanes publish. The
    plan lane keeps trade_allowed green BY DESIGN — one position-cap gate
    refuses any unreadable bridge in ONE place — and the signal lane flips the
    policy itself only because its position read happens earlier, inside
    check_signals, where there is no downstream gate to defer to. In BOTH
    lanes the ENTRY VERDICT is the same.

RUNNING THIS TEST RED EXPOSED THE REAL GAP, which is subtler than the backlog
described: the position-cap gate (auto_executor Check 5) fires BEFORE the
account-policy branch (Check 2) can append the dark-bridge reason, because
b214's fail-closed *is* the cap. So on the plan lane a dark bridge is
reportable ONLY through the flag on the policy, never through the b219
executor reason; that reason is reachable only on the signal lane, where the
policy flips first. b219's own tests never pinned this — they always set
open_positions=cap AND trade_allowed=False together, which is the one
combination that lets the reason fire. That combination is exactly what the
SIGNAL lane produces and the plan lane does not. Pinning it here is the fix:
the invariant is now stated once, in the order the code actually runs, and
that ordering IS the contract.

Properties pinned, on the real production paths (no patched policy):
  1. the plan lane's own policy stays trade_allowed=True on a dark bridge —
     the deferral, and the trap for any trade_allowed-only reader;
  2. the plan lane refuses that policy at the EXECUTOR'S position-cap gate,
     and the flag travels on the policy — never as an executor reason;
  3. a HEALTHY FLAT book is refused nowhere — flag absent, cap not consumed,
     gate opens — so an honest flat never claims the bridge is dark (b219);
  4. a REAL open position on a healthy book reports max_positions, never the
     dark-bridge flag: the two incidents stay distinguishable at the policy
     (the b214/b219 contract, pinned from the plan-lane side);
  5. the entry verdict is identical across lanes on the same dark bridge.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines import auto_executor as AE  # noqa: E402
from engines import signal_listener as SL  # noqa: E402
import hermes_runtime  # noqa: E402 (b41: leak half of the storage patch closed)
from hermes_runtime import _performance_and_policy  # noqa: E402

FLAG = "positions_unreadable"
DARK_REASON = "bridge_dark_positions_unreadable"
CAP = AE.MAX_OPEN_POSITIONS

_NOW = datetime.now(timezone.utc)


class _Bridge:
    """Minimal bridge stub: the read-only surface only — no order endpoint.

    get_account/get_positions/get_history_deals/get_tick is the entire surface
    either lane reads before an order, so nothing here can place a trade.
    """

    def __init__(self, *, dark_positions: bool = False,
                 positions: list | None = None, balance: float = 5000.0):
        self._dark = dark_positions
        self._positions = [] if positions is None else positions
        self._account = {
            "ok": True,
            "data": {
                "balance": balance,
                "equity": balance,      # no drawdown, healthy book
                "margin": 0.0,
                "margin_free": balance,
            },
        }

    # --- read-only bridge calls only (never send_order) ---

    def get_account(self):
        return self._account

    def get_positions(self, symbol="XAUUSD"):
        if self._dark:
            raise RuntimeError("bridge dark: positions endpoint refused")
        return {"ok": True, "data": self._positions}

    def get_history_deals(self, symbol="XAUUSD", days=7):
        return {"ok": True, "data": []}

    def get_tick(self, symbol="XAUUSD"):
        return {"ok": True, "bid": 4449.8, "ask": 4450.2, "time": 1}

    def get_price_band(self, symbol="XAUUSD", hours=24):
        return {"ok": True, "data": []}


def _dark_bridge():
    return _Bridge(dark_positions=True)


def _healthy_flat_bridge():
    return _Bridge(dark_positions=False)


def _proposal() -> dict:
    """A blueprint the executor accepts on a healthy book, in the proposal
    shape evaluate_proposal actually reads (blueprint + grade). RR 3.0."""
    return {
        "blueprint": {
            "symbol": "XAUUSD",
            "side": "SELL",
            "entry_price": 4450.0,
            "sl": 4462.0,      # 12.0 stop ABOVE entry (SELL)
            "tp": 4414.0,      # 36.0 target BELOW entry -> RR 3.0
            "atr": 5.0,
        },
        "grade": "B",
    }


def _plan_policy(bridge) -> dict:
    """The plan lane's real policy for this bridge (hermes_runtime)."""
    return _performance_and_policy(
        bridge, bridge.get_account(), _NOW)["account_policy"]


def _evaluate(policy: dict, stub_ambient: bool = True) -> dict:
    """Run the executor's gate chain on a policy. Ambient gates (market hours
    + cooldown) are stubbed open so the ONLY thing under test is the
    position-cap / account-policy contract — the b136/b219 pattern."""
    if not stub_ambient:
        return AE.evaluate_proposal(_proposal(), policy, {}, {}, None)
    from engines import cooldown as CD

    real_open = AE.is_market_open
    real_cd = CD.check_entry_cooldown
    try:
        AE.is_market_open = lambda *a, **k: True
        CD.check_entry_cooldown = lambda now=None: {"allowed": True}
        return AE.evaluate_proposal(_proposal(), policy, {}, {}, None)
    finally:
        AE.is_market_open = real_open
        CD.check_entry_cooldown = real_cd


def _signal_executions(dark: bool) -> list[dict]:
    """The signal lane's verdict on one signal, via the PUBLIC entrypoint.

    run_signal_check builds its own policy from the same two real emitters the
    plan lane uses (kill_switch + risk.assess_account_policy), reads positions
    with bridge.get_positions, and then runs evaluate_proposal. On a dark
    bridge the position read throws inside check_signals, whose fail-closed
    arms set the flag + trade_allowed=False — the entry is refused IN the
    policy and the executor is never reached with a policy that could allow a
    blind entry.

    Order attempts are guarded from the production path: dry_run short-
    circuits execute_trade before any bridge call, and the stub below also
    raises if ever reached with dry_run off — a read-only contract test that
    never executes a trade.
    """
    bridge = _Bridge(dark_positions=dark)
    _orig_fetch = SL.fetch_new_messages
    _orig_execute = AE.execute_trade
    _orig_group = SL.os.environ.get("TELEGRAM_SIGNAL_GROUP")
    # b254: check_signals dedupes on (chat_id, message_id) AND on a hash of the
    # signal content, persisting both to the real listener_state.json. Without
    # isolating that state a repeat call with the same fixture text is silently
    # dropped as a re-broadcast, and the lane produces no verdict at all.
    _orig_load = SL._load_state
    _orig_save = SL._save_state
    _test_state = {"last_update_id": 0, "last_check": "", "seen_message_ids": {}}
    SL._load_state = lambda: dict(_test_state)
    SL._save_state = lambda st: _test_state.update(st)
    # b221 fix: run_signal_check calls evaluate_proposal through the SIGNAL
    # lane's OWN imports, so the ambient gates have to be stubbed there too —
    # the same _evaluate() discipline. auto_executor already imported
    # is_market_open by bare name at module level, so patching AE.is_market_open
    # is a no-op; the real binding lives on engines.market_hours.
    from engines import market_hours as MH
    from engines import cooldown as CD
    _orig_open = MH.is_market_open
    _orig_cd = CD.check_entry_cooldown
    # auto_executor captured is_market_open by bare name at import time, so
    # patching MH.is_market_open alone is a no-op on the AE path — patch BOTH
    # bindings (the b41 binding discipline this repo enforces in audit).
    # check_entry_cooldown stays on CD only: AE imports it lazily at line 316.
    _orig_ae_open = AE.is_market_open
    SL.os.environ["TELEGRAM_SIGNAL_GROUP"] = "-100contract"
    # b221: the live data/xau_plan holds whatever bias the market has today; a
    # bullish plan vetoes this SELL fixture with direction_conflict and the
    # lane is never exercised. Pin a bearish plan so the contract is actually
    # tested against today's plan state.
    from engines import storage as _st
    _orig_plan = _st.load_current_plan
    _fake = lambda *a, **k: {
        "bias": "bearish", "side": "SELL",
        "quality": {"confidence": 0.8}, "timestamp": _NOW.timestamp(),
    }
    _st.load_current_plan = _fake
    # b41: hermes_runtime from-imports load_current_plan at module level and
    # calls it by bare name, so the storage patch is a NO-OP on that path.
    # Mirror the fake onto the binding hermes_runtime actually holds, and
    # restore both in finally (same shape as test_b211c_single_account_read).
    _orig_rt_plan = hermes_runtime.load_current_plan
    hermes_runtime.load_current_plan = _fake
    SL.fetch_new_messages = lambda: [{
        "update_id": 1,
        "chat_id": "-100contract",
        "chat_title": "t",
        "from": "x",
        "text": "SELL XAUUSD 4450 SL 4462 TP 4414",
        "date": int(_NOW.timestamp()) - 30,
    }]

    def _no_trade(command, br=None, dry_run=False, idempotency_key=None):
        # dry_run returns early with executed=False and no bridge call; any
        # other path means a gate let a live order through — fail loudly.
        if dry_run:
            return {"ok": True, "dry_run": True, "would_execute": command,
                    "executed": False}
        raise AssertionError("b221 contract test must never send an order")

    AE.execute_trade = _no_trade
    MH.is_market_open = lambda *a, **k: True
    AE.is_market_open = lambda *a, **k: True
    CD.check_entry_cooldown = lambda now=None: {"allowed": True}
    try:
        return SL.run_signal_check(bridge, dry_run=True).get("executions", [])
    finally:
        SL.fetch_new_messages = _orig_fetch
        AE.execute_trade = _orig_execute
        SL._load_state = _orig_load
        SL._save_state = _orig_save
        MH.is_market_open = _orig_open
        AE.is_market_open = _orig_ae_open
        _st.load_current_plan = _orig_plan
        hermes_runtime.load_current_plan = _orig_rt_plan
        CD.check_entry_cooldown = _orig_cd
        if _orig_group is None:
            SL.os.environ.pop("TELEGRAM_SIGNAL_GROUP", None)
        else:
            SL.os.environ["TELEGRAM_SIGNAL_GROUP"] = _orig_group


class TestPlanLaneDefersBlockToExecutor(unittest.TestCase):
    """(1)+(2): on a dark bridge the plan lane's policy stays trade_allowed and
    the EXECUTOR'S position-cap gate is the refusal — the deferral the
    contract names, and the trap for a trade_allowed-only reader."""

    def test_plan_lane_policy_defers_and_flags(self):
        pol = _plan_policy(_dark_bridge())
        # THE DEFERRAL (this is the contract's plan-lane half, by design):
        self.assertTrue(
            pol.get("trade_allowed"),
            "the plan lane keeps trade_allowed=True and defers the block to "
            "the executor's position-cap gate (b45/b214)")
        self.assertEqual(pol.get("regime"), "normal")
        # THE FLAG: the reason the block exists is published honestly.
        self.assertTrue(pol.get(FLAG), "a dark bridge must publish the cause")
        # and the cap is consumed — this is what actually does the refusing.
        self.assertEqual(int(pol.get("open_positions", -1)), CAP)

    def test_executor_refuses_the_same_policy(self):
        pol = _plan_policy(_dark_bridge())
        v = _evaluate(pol)
        self.assertFalse(v.get("execute"),
                         "the executor must refuse an unreadable bridge")
        # THE TRAP, pinned openly: the policy alone would have said yes.
        self.assertTrue(pol.get("trade_allowed"))

    def test_dark_bridge_reports_via_the_flag_never_an_executor_reason(self):
        """The ordering gap this run exposed: the position-cap gate (Check 5)
        fires before the account-policy branch (Check 2) can append the
        dark-bridge reason, because b214's fail-closed *is* the cap. So on the
        PLAN lane a dark bridge is reportable only through the flag on the
        policy, never as an executor reason. b219's tests never pinned this —
        they set open_positions=cap AND trade_allowed=False together, the one
        combination that lets the reason fire. That combination is what the
        SIGNAL lane produces and this lane does not."""
        pol = _plan_policy(_dark_bridge())
        v = _evaluate(pol)
        self.assertFalse(v.get("execute"))
        # the cap did the refusing — this is the plan lane's refusal point.
        self.assertIn(f"max_positions_{CAP}", v.get("reasons", []))
        # the b219 reason is NOT emitted here: the cap fired first. It is
        # reachable only on the signal lane (the signal half of property 2).
        self.assertNotIn(DARK_REASON, v.get("reasons", []))
        # ...but the operator still sees the cause, on the policy itself.
        self.assertTrue(pol.get(FLAG))

    def test_executor_would_open_on_a_healthy_flat_book(self):
        # anti-goldbricking: the gate must not block just because it can.
        pol = _plan_policy(_healthy_flat_bridge())
        v = _evaluate(pol)
        self.assertTrue(v.get("execute"),
                        "a healthy flat book must pass the position gate")

    def test_flat_book_never_claims_the_bridge_is_dark(self):
        pol = _plan_policy(_healthy_flat_bridge())
        self.assertFalse(pol.get(FLAG, False),
                         "an honest flat must not claim positions_unreadable")
        self.assertEqual(int(pol.get("open_positions", -1)), 0)


class TestRealPositionIsNotAnOutage(unittest.TestCase):
    """(4): a real open position on a healthy book reports max_positions and
    never the dark-bridge flag — the two incidents stay distinguishable at the
    policy, which is the whole reason b214 published the flag (the plan-lane
    side of the b219 contract)."""

    def _real_position_policy(self) -> dict:
        bridge = _Bridge(dark_positions=False,
                         positions=[{"ticket": 777, "type": 1}])
        return _plan_policy(bridge)

    def test_real_position_does_not_set_the_dark_flag(self):
        pol = self._real_position_policy()
        self.assertFalse(pol.get(FLAG, False),
                         "a real position is not a bridge outage")
        self.assertEqual(int(pol.get("open_positions", -1)), 1)

    def test_executor_reports_a_real_position_as_max_positions(self):
        pol = self._real_position_policy()
        v = _evaluate(pol)
        self.assertFalse(v.get("execute"))
        self.assertIn("max_positions_1", v.get("reasons", []))
        self.assertNotIn(DARK_REASON, v.get("reasons", []),
                         "a real position must not read as a dark bridge")


class TestSignalLaneRefusesInPolicy(unittest.TestCase):
    """(2): the signal lane's own policy flips on the same flag — the other
    half of the contract — and it never reaches the executor."""

    def test_dark_bridge_refused_before_the_executor(self):
        # The book is HEALTHY (no drawdown, no streak) — so the ONLY thing
        # refusing this entry is the unreadable positions reply. The
        # kill-switch half agrees the book is fine, proving the refusal comes
        # from the dark bridge and not from a money gate.
        bridge = _dark_bridge()
        account = bridge.get_account()
        acct = account.get("data", account) or {}
        from engines.kill_switch import check_kill_switch
        _kill = check_kill_switch(
            balance=float(acct.get("balance", 0) or 0),
            equity=float(acct.get("equity", 0) or 0),
            daily_pnl=0.0,
            consecutive_losses=0,
            margin_free=float(acct.get("margin_free", 0) or 0),
            margin=float(acct.get("margin", 0) or 0),
            now=_NOW)
        self.assertFalse(_kill.get("halted", False),
                         "the book is healthy; the refusal is the dark bridge")

        # The dark bridge raises inside check_signals → both of its error arms
        # set the flag and trade_allowed=False (b29/b214 fail-closed shape),
        # so the entry is refused IN the policy and never reaches the
        # executor — the signal-lane half of the contract.
        execs = _signal_executions(dark=True)
        self.assertTrue(execs, "the lane must produce a verdict for the signal")
        self.assertFalse(any(e.get("executed") for e in execs),
                         "a dark bridge must never produce an execution")
        for e in execs:
            self.assertNotEqual(e.get("verdict"), "execute",
                                "no execution may be recorded")
            self.assertTrue(e.get("reasons"),
                            "a refused entry must say why")

    def test_flat_book_reaches_the_executor_gates(self):
        # healthy flat: no flag, the lane runs the executor's chain and the
        # proposal clears every gate (dry_run keeps executed=False by design).
        execs = _signal_executions(dark=False)
        self.assertTrue(execs, "the lane must produce a verdict for the signal")
        self.assertEqual(execs[0].get("verdict"), "execute",
                         "a healthy flat book must clear the lane's gates")
        self.assertFalse(any(e.get("executed") for e in execs))


class TestLanesAgreeOnTheEntryVerdict(unittest.TestCase):
    """(5): whatever each lane does internally, the ENTRY VERDICT is identical
    on the same dark bridge. That is the whole point of naming the invariant
    once."""

    def test_dark_bridge_same_verdict_both_lanes(self):
        # plan lane: defers to the executor's position-cap gate
        plan_pol = _plan_policy(_dark_bridge())
        plan = _evaluate(plan_pol)
        self.assertFalse(plan.get("execute"))
        # signal lane: refuses in the policy — same entry verdict. This is the
        # one combination b219's tests used (cap + trade_allowed=False), which
        # only the signal lane actually produces. balance/equity keys are what
        # assess_account_policy emits on the real path.
        signal_pol = {"trade_allowed": False, "regime": "bridge_dark",
                      "open_positions": CAP, FLAG: True,
                      "balance": 5000.0, "equity": 5000.0}
        signal = _evaluate(signal_pol)
        self.assertFalse(signal.get("execute"))

    def test_flat_book_same_verdict_both_lanes(self):
        # plan lane: the real policy, cap not consumed
        plan_pol = _plan_policy(_healthy_flat_bridge())
        plan = _evaluate(plan_pol)
        self.assertTrue(plan.get("execute"))
        # signal lane on a healthy flat book: the executor clears too
        signal_pol = {"trade_allowed": True, "regime": "normal",
                      "open_positions": 0, "balance": 5000.0,
                      "equity": 5000.0}
        signal = _evaluate(signal_pol)
        self.assertTrue(signal.get("execute"))


if __name__ == "__main__":
    unittest.main()
