#!/usr/bin/env python3
"""b140 — SIGNAL-LANE REGIME CENSUS: does each regime the account-health policy
can EMIT reach BOTH consumers on the signal path?

b137 filed this item from a read of `engines/signal_listener.check_signals`,
where the `account_policy` handed to `evaluate_signal` is built with `regime`
hardcoded to "normal" (or "halted" from the kill switch), and concluded "a
signal arriving at 3% drawdown trades at full size".

The signal lane builds TWO policies, so that sentence is only true of one of
them:

    check_signals()    -> policy #1 (hardcoded regime) -> engines.signal_decision
                          .evaluate_signal  — the 8-check SCORER (verdict+grade)
    run_signal_check() -> policy #2 from hermes_runtime._performance_and_policy
                          (the REAL risk.assess_account_policy) -> auto_executor
                          .evaluate_proposal — the SIZER and every hard gate

This script therefore asks the question in the FRAME the code runs in (b113) and
measures two observables per arm, through the real functions:

  Q1 SIZE  — run the whole real `run_signal_check` on an injected fake bridge
     whose account numbers put the real chain into the arm's regime, and read
     the LOT that comes back out. Observable = lot / order count.
  Q2 SCORE — capture (by spying on the call) the account_policy that
     `check_signals` ACTUALLY passes to `evaluate_signal`, and compare it with
     the real `assess_account_policy` output for the same account. Observable =
     the scorer's verdict.

Every arm is CHECKED, not trusted (b122: an arm must be the rule it is named
for): the census re-derives the regime the lane really computed
(`_performance_and_policy` on the same bridge) and raises if it differs from
the arm's label. The first draft of this round had exactly that defect — a
"defensive" arm that fed only an equity number, so the loss-streak branch never
fired and the lane ran "normal" while the table said defensive.

Regime NAMES are discovered by AST-scanning risk.py and mapped back to
branch-hitting account numbers by calling the real emitter (b109/b136: never
restate a literal you can probe).

Read-only: no real bridge (a fake is injected), no order endpoint is ever
contacted by this script, and the whole state tree is redirected to a temp dir.
Writes ONE new ledger under data/backtest/. Post-processing is a PURE function
of the collected rows (b127/b128) so scripts/b127_producer_reproduction.py can
re-execute it against the frozen ledger.
"""
from __future__ import annotations

import ast
import copy
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(str(_ROOT / ".env"))

from engines import risk as R                                   # noqa: E402
from engines import auto_executor as AE                         # noqa: E402
from engines import signal_decision as SD                       # noqa: E402
from engines import signal_listener as SL                       # noqa: E402
from engines.risk import assess_account_policy                  # noqa: E402
# Import hermes_runtime at MODULE level, not inside _warm_state: it binds
# `assess_account_policy` into its own namespace at import time. A lazy first
# import could land while a test has patched the emitter, permanently poisoning
# the sizer's binding for the rest of the process.
import hermes_runtime                                           # noqa: E402

LEDGER = _ROOT / "data" / "backtest" / "b140_signal_lane_regime_census.json"

SIGNAL_TEXT = "SELL XAUUSD 4450 SL 4460 TP 4425"
SIGNAL_ENTRY, SIGNAL_SL, SIGNAL_TP = 4450.0, 4460.0, 4425.0
BALANCE = 5000.0
STOP_DISTANCE = abs(SIGNAL_ENTRY - SIGNAL_SL)


# ── discovery: what can the emitter say? ────────────────────────────────────

def emittable_regimes() -> list[str]:
    """Every regime string risk.assess_account_policy can assign (AST scan)."""
    src = Path(R.__file__).read_text(encoding="utf-8")
    found: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.FunctionDef)
                and node.name == "assess_account_policy"):
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                        and getattr(sub.targets[0], "id", None) == "regime"
                        and isinstance(sub.value, ast.Constant)
                        and isinstance(sub.value.value, str)
                        and sub.value.value not in found):
                    found.append(sub.value.value)
    return found


def _losing_deals(n: int, base_ts: float, each: float = -25.0) -> list[dict]:
    """n closed losing deals in the shape the real bridge feed returns."""
    return [{"ticket": 900001 + i, "time": base_ts - 600 * (i + 1),
             "profit": each, "entry": 1, "symbol": "XAUUSD"}
            for i in range(n)]


def arms(now: datetime | None = None) -> list[dict]:
    """One arm per regime the emitter can produce, built from the emitter's OWN
    thresholds (read below, never copied), plus the account numbers the fake
    bridge feeds through the real chain.

    `deals` matters: daily_pnl and loss_streak are NOT account fields — the
    real chain derives them from the closed-deal feed via
    compute_performance_state, so an arm that wants a streak must supply deals.
    """
    now = now or datetime.now(timezone.utc)
    ts = now.timestamp()
    return [
        {"label": "normal", "equity": BALANCE, "margin": 0.0,
         "margin_free": BALANCE, "deals": []},
        # defensive via loss_streak >= 2 (needs the deal feed, not an account
        # field) — also the arm that fires DEFCON YELLOW at the same time.
        {"label": "defensive_streak", "equity": BALANCE, "margin": 0.0,
         "margin_free": BALANCE, "deals": _losing_deals(2, ts)},
        # defensive via daily loss >= 1% of balance, WITHOUT a streak (one big
        # loss) — the arm that isolates the daily_pnl branch from loss_streak.
        {"label": "defensive_daily_loss", "equity": BALANCE, "margin": 0.0,
         "margin_free": BALANCE,
         "deals": _losing_deals(1, ts, each=-round(BALANCE * 0.011, 2))},
        # recovery: drawdown >= 2.5% (equity/balance only, no deals)
        {"label": "recovery_dd", "equity": round(BALANCE * 0.974, 2),
         "margin": 0.0, "margin_free": BALANCE, "deals": []},
        # locked: drawdown >= 5%
        {"label": "locked_dd", "equity": round(BALANCE * 0.949, 2),
         "margin": 0.0, "margin_free": BALANCE, "deals": []},
        # locked by margin health at a ratio the KILL SWITCH does not halt
        # (kill MARGIN_RATIO_MIN=10 < policy margin_ratio<20) — the state where
        # a hardcoded "normal" in the scorer is most misleading.
        {"label": "locked_margin", "equity": BALANCE, "margin": 1000.0,
         "margin_free": 15000.0, "deals": []},
    ]


def real_policy(arm: dict) -> dict:
    """The emitter, called directly with the arm's account numbers + the state
    the deal feed would produce."""
    return assess_account_policy(
        balance=BALANCE, equity=arm["equity"],
        free_margin=arm["margin_free"], margin=arm["margin"],
        daily_pnl=round(sum(d["profit"] for d in arm["deals"]), 2),
        loss_streak=len(arm["deals"]), open_positions=0)


def _warm_state(bridge, now: datetime):
    """Populate performance_state.json ONCE before the lane runs.

    Why this is not a hack: `compute_performance_state` returns the ROLLOVER
    branch (daily_pnl=0.0, loss_streak=0) whenever the stored day != today, so
    the FIRST cycle of every UTC day — on the real box as here — classifies the
    account as "normal" no matter what yesterday did (b88 carried `recent_closed`
    through the rollover for DEFCON, deliberately NOT daily_pnl/loss_streak).
    Without the warm-up, every deal-derived arm of this census would measure
    that rollover artefact instead of the regime it is named for. The warm-up
    reproduces the steady state the lane actually trades in.
    """
    import hermes_runtime
    return hermes_runtime._performance_and_policy(
        bridge, bridge.get_account() or {}, now)


# ── the fake bridge ─────────────────────────────────────────────────────────

class RegimeBridge:
    """Read-only bridge whose numbers put the real chain in the arm's regime.
    send_order/send_pending RECORD and report success; nothing else writes."""

    def __init__(self, arm: dict):
        self.arm = arm
        self.orders: list[dict] = []

    def get_tick(self, symbol="XAUUSD"):
        return {"ok": True, "ask": SIGNAL_ENTRY, "bid": SIGNAL_ENTRY}

    def get_account(self):
        return {"data": {"balance": BALANCE, "equity": self.arm["equity"],
                         "margin": self.arm["margin"],
                         "margin_free": self.arm["margin_free"],
                         "positions": 0}}

    def get_positions(self, symbol="XAUUSD"):
        return {"data": []}

    def get_history_deals(self, symbol="XAUUSD", days=7):
        return {"ok": True, "data": list(self.arm["deals"])}

    def get_price_band(self, symbol="XAUUSD", hours=24):
        return {"low": SIGNAL_ENTRY - 50, "high": SIGNAL_ENTRY + 50}

    def send_order(self, **kw):
        self.orders.append(kw)
        return {"ok": True, "ticket": 999001}

    def send_pending(self, **kw):
        self.orders.append(kw)
        return {"ok": True, "ticket": 999002}


# ── harness: run the real lane with the outside world stubbed ───────────────

def _run_lane(arm: dict):
    """Drive the REAL signal lane on one arm.

    Returns the observables plus BOTH policies the lane itself used, captured
    by spying on the two call sites (b122: measure what the code was given,
    never re-call the producer and assume the lane saw the same thing — the
    first such call here silently differed from the lane's own, because
    compute_performance_state's day-rollover branch zeroes daily_pnl/streak on
    a cold state file).
    """
    import engines.storage as st
    import engines.economic_calendar as ec
    import hermes_runtime

    root = Path(tempfile.mkdtemp(prefix="b140_"))
    (root / "data" / "xau_plan").mkdir(parents=True, exist_ok=True)
    os.environ["HERMES_DATA_ROOT"] = str(root)
    os.environ["TELEGRAM_SIGNAL_GROUP"] = "-100b140"

    now = datetime.now(timezone.utc)
    cold = _warm_state(RegimeBridge(arm), now)   # COLD-START reading (see below)
    _warm_state(RegimeBridge(arm), now)          # → steady state on disk
    captured: dict = {}
    rows: list[dict] = []

    orig = {"fetch": SL.fetch_new_messages, "log": SL._log_signal,
            "plan": st.load_current_plan, "cal": ec.fetch_economic_calendar,
            "exec_log": st.append_execution_log,
            "evaluate_signal": SD.evaluate_signal,
            "evaluate_proposal": AE.evaluate_proposal}

    def _spy_eval(signal, hermes_analysis, account_policy, **kw):
        captured["scorer_policy"] = copy.deepcopy(account_policy)
        return orig["evaluate_signal"](signal, hermes_analysis, account_policy, **kw)

    def _spy_proposal(proposal, account_policy, performance_state, plan, bridge=None):
        captured["sizer_policy"] = copy.deepcopy(account_policy)
        captured["sizer_perf"] = copy.deepcopy(performance_state)
        return orig["evaluate_proposal"](proposal, account_policy,
                                         performance_state, plan, bridge)

    def _msgs():
        return [{"update_id": 1, "chat_id": "-100b140", "chat_title": "t",
                 "from": "b140", "text": SIGNAL_TEXT,
                 "date": datetime.now(timezone.utc).timestamp() - 30}]

    bridge = RegimeBridge(arm)
    try:
        SL.fetch_new_messages = _msgs
        SL._log_signal = lambda *a, **k: None
        st.load_current_plan = lambda p: {"bias": "bearish", "quality": {}}
        ec.fetch_economic_calendar = lambda *a, **k: {"events": []}
        st.append_execution_log = lambda base_dir, row: rows.append(dict(row))
        SD.evaluate_signal = _spy_eval
        AE.evaluate_proposal = _spy_proposal
        res = SL.run_signal_check(bridge, dry_run=False)
    finally:
        SL.fetch_new_messages = orig["fetch"]
        SL._log_signal = orig["log"]
        st.load_current_plan = orig["plan"]
        ec.fetch_economic_calendar = orig["cal"]
        st.append_execution_log = orig["exec_log"]
        SD.evaluate_signal = orig["evaluate_signal"]
        AE.evaluate_proposal = orig["evaluate_proposal"]
        os.environ.pop("HERMES_DATA_ROOT", None)

    ex = (res.get("executions") or [{}])[0]
    sizer = captured.get("sizer_policy") or {}
    perf = captured.get("sizer_perf") or {}
    return {
        "verdict": ex.get("verdict"),
        "reasons": ex.get("reasons", []),
        "lot": ex.get("lot"),
        "orders_sent": len(bridge.orders),
        "logged_risk_usd": (rows or [{}])[0].get("risk_usd"),
        "scorer_saw": captured.get("scorer_policy"),
        "sizer_saw_regime": sizer.get("regime"),
        "sizer_saw_trade_allowed": sizer.get("trade_allowed"),
        "sizer_saw_daily_pnl": perf.get("daily_pnl"),
        "sizer_saw_loss_streak": perf.get("loss_streak"),
        "cold_start_regime": cold["account_policy"].get("regime"),
    }


def score_only(policy: dict) -> dict:
    """Run the real scorer on ONE policy view for the fixed test signal."""
    parsed = {"symbol": "XAUUSD", "side": "SELL", "confidence": 0.9,
              "entry": SIGNAL_ENTRY, "sl": SIGNAL_SL, "tp": SIGNAL_TP,
              "rr_ratio": round(abs(SIGNAL_TP - SIGNAL_ENTRY) / STOP_DISTANCE, 2),
              "computed_rr": 0, "warnings": [], "lot": None}
    d = SD.evaluate_signal(parsed, {"bias": "bearish", "quality": {}}, policy,
                           macro_filter={"allowed": True, "events": []})
    return {"verdict": d["verdict"], "score": d["score"],
            "trade_allowed": d["trade_allowed"], "reasons": d["reasons"]}


def executor_by_name(regime: str) -> dict:
    """Cross-check the SIZER on the regime NAME alone (b136/b137 template)."""
    proposal = {"blueprint": {"side": "SELL", "entry_price": SIGNAL_ENTRY,
                              "sl": SIGNAL_SL, "tp": SIGNAL_TP,
                              "symbol": "XAUUSD"},
                "monitor_action": "signal_market_entry", "grade": "B"}
    perf = {"day": datetime.now(timezone.utc).date().isoformat(),
            "daily_pnl": 0.0, "trades_today": 0, "loss_streak": 0,
            "recent_closed": []}
    pol = {"trade_allowed": True, "regime": regime, "open_positions": 0,
           "balance": BALANCE, "max_positions_allowed": 1}
    r = AE.evaluate_proposal(proposal, pol, perf, {}, bridge=None)
    return {"regime": regime, "execute": r.get("execute"),
            "reason": r.get("reason"),
            "lot": (r.get("command") or {}).get("lot"),
            "risk_pct": r.get("risk_pct"),
            "tight": regime in AE.TIGHT_REGIMES,
            "blocks": regime in AE.STOP_TRADING_REGIMES}


def collect() -> dict:
    names = emittable_regimes()
    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "emittable_regimes": names,
           "signal": {"text": SIGNAL_TEXT, "entry": SIGNAL_ENTRY,
                      "sl": SIGNAL_SL, "tp": SIGNAL_TP, "balance": BALANCE},
           "arms": [], "executor_by_name": []}
    for arm in arms():
        pol = real_policy(arm)
        lane = _run_lane(arm)
        # b122 CHECK: is this arm the rule it is named for? The sizer's view is
        # the strongest evidence, but after the b140 tightening a locked arm
        # can be skipped by the SCORER before evaluate_proposal is ever reached
        # — then the scorer's captured regime is the proof the arm fired.
        observed = lane["sizer_saw_regime"] or (lane["scorer_saw"] or {}).get("regime")
        expected = pol["regime"]
        if observed != expected:
            raise RuntimeError(
                f"b140: arm '{arm['label']}' expected regime {expected!r} but "
                f"the lane computed {observed!r} — the arm is not the rule it "
                f"is named for (b122)")
        scorer_view = lane["scorer_saw"] or {}
        out["arms"].append({
            "label": arm["label"],
            "real_policy": {"regime": pol["regime"],
                            "trade_allowed": pol["trade_allowed"],
                            "risk_multiplier": pol["risk_multiplier"],
                            "drawdown_pct": pol["drawdown_pct"],
                            "margin_ratio": pol["margin_ratio"]},
            "lane": lane,
            "scorer_view_regime": scorer_view.get("regime"),
            "scorer_view_trade_allowed": scorer_view.get("trade_allowed"),
            "score_on_scorer_view": score_only(dict(
                {"trade_allowed": True, "regime": "normal", "open_positions": 0,
                 "balance": BALANCE}, **scorer_view)),
            "score_on_real_policy": score_only(pol),
        })
    for name in sorted(set(names) | set(AE.TIGHT_REGIMES)
                       | set(AE.STOP_TRADING_REGIMES)):
        out["executor_by_name"].append(executor_by_name(name))
    return out


def derive(rows: dict) -> dict:
    """PURE post-processing of the collected rows (b127/b128 re-executable)."""
    normal = next((a["lane"]["lot"] for a in rows["arms"]
                   if a["real_policy"]["regime"] == "normal"), None)
    out = {"sizing": {}, "scoring": {}}
    for a in rows["arms"]:
        lane, reg = a["lane"], a["real_policy"]["regime"]
        out["sizing"][a["label"]] = {
            "regime": reg, "lot": lane["lot"], "normal_lot": normal,
            "orders_sent": lane["orders_sent"], "verdict": lane["verdict"],
            "shrunk": (lane["lot"] is not None and normal is not None
                       and lane["lot"] < normal),
            "blocked": lane["orders_sent"] == 0,
        }
        sv, rv = a["score_on_scorer_view"], a["score_on_real_policy"]
        out["scoring"][a["label"]] = {
            "regime": reg,
            "scorer_saw_regime": a["scorer_view_regime"],
            "scorer_verdict": sv["verdict"], "real_verdict": rv["verdict"],
            "blind": sv["verdict"] != rv["verdict"],
        }
    out["sizing_blocks_locked"] = all(
        v["blocked"] for v in out["sizing"].values()
        if v["regime"] in AE.STOP_TRADING_REGIMES)
    out["sizing_shrinks_tight"] = all(
        v["shrunk"] for v in out["sizing"].values()
        if v["regime"] in AE.TIGHT_REGIMES)
    out["scoring_blind_arms"] = sorted(
        k for k, v in out["scoring"].items() if v["blind"])
    out["scoring_sees_real_regime"] = all(
        v["scorer_saw_regime"] == v["regime"] for v in out["scoring"].values())
    return out


def self_check(d: dict) -> list[str]:
    """Re-audit a frozen ledger: every claim in `derived` must still follow
    from the collected rows (b127/b128: post-processing must be re-executable
    and drift must be loud, not silent)."""
    problems: list[str] = []
    try:
        fresh = derive({"arms": d["arms"],
                        "executor_by_name": d["executor_by_name"]})
    except Exception as e:
        return [f"derive() raised on the frozen ledger: {e}"]
    old = d.get("derived", {})
    for key in ("sizing_blocks_locked", "sizing_shrinks_tight",
                "scoring_sees_real_regime"):
        if bool(old.get(key)) != bool(fresh.get(key)):
            problems.append(f"{key}: ledger={old.get(key)} fresh={fresh.get(key)}")
    if sorted(old.get("scoring_blind_arms", [])) != sorted(
            fresh.get("scoring_blind_arms", [])):
        problems.append(
            f"scoring_blind_arms: ledger={old.get('scoring_blind_arms')} "
            f"fresh={fresh.get('scoring_blind_arms')}")
    # the headline invariants themselves (a ledger can be self-consistent and
    # still document a regression — e.g. blind arms re-derive to [] == []):
    if not fresh.get("sizing_blocks_locked"):
        problems.append("locked regimes no longer block the signal lane")
    if not fresh.get("sizing_shrinks_tight"):
        problems.append("tight regimes no longer shrink the signal lane lot")
    if fresh.get("scoring_blind_arms"):
        problems.append(f"scorer blind again: {fresh['scoring_blind_arms']}")
    return problems


def main() -> dict:
    rows = collect()
    rows["derived"] = derive(rows)
    rows["_self_check_problems"] = self_check(rows)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    return rows


if __name__ == "__main__":
    data = main()
    if data["_self_check_problems"]:
        print("SELF-CHECK PROBLEMS:")
        for p in data["_self_check_problems"]:
            print("  -", p)
        sys.exit(2)
    d = data["derived"]
    print("emittable regimes:", data["emittable_regimes"])
    print("\nQ1 SIZING LANE (real run_signal_check → lot actually sent):")
    for k, v in d["sizing"].items():
        print(f"  {k:<22} regime={v['regime']:<10} lot={v['lot']} "
              f"(normal {v['normal_lot']}) orders={v['orders_sent']} "
              f"shrunk={v['shrunk']} blocked={v['blocked']}")
    print(f"  -> locked blocked: {d['sizing_blocks_locked']} | "
          f"tight shrunk: {d['sizing_shrinks_tight']}")
    print("\nQ2 SCORING LANE (what evaluate_signal was actually given):")
    for k, v in d["scoring"].items():
        print(f"  {k:<22} real={v['regime']:<10} scorer_saw="
              f"{str(v['scorer_saw_regime']):<10} verdict "
              f"{v['scorer_verdict']} vs real {v['real_verdict']} "
              f"blind={v['blind']}")
    print(f"  -> blind arms: {d['scoring_blind_arms']} | "
          f"scorer sees real regime: {d['scoring_sees_real_regime']}")
    print(f"\nledger: {LEDGER}")
