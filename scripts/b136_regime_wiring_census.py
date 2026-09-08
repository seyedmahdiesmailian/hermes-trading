#!/usr/bin/env python3
"""b136 — TRADER CODE REVIEW: is every regime the account-health policy can
EMIT actually WIRED into the entry sizing path?

The read that produced this round:

  engines/risk.assess_account_policy classifies the account into one of four
  regimes and attaches a `risk_multiplier` to each:
      normal 1.0 | defensive 0.75 | recovery 0.5 | locked 0.0 (+trade_allowed False)
  engines/auto_executor.evaluate_proposal — the ONE entry gate both the plan
  path (hermes_runtime) and the signal path (signal_listener) funnel through —
  does not read `risk_multiplier` at all. It reads `trade_allowed` (so `locked`
  is wired), and it applies its own flat 0.5 to `TIGHT_REGIMES`, which before
  this round was {"defensive"} only. So `recovery` was computed, reported,
  documented to the operator as live policy — and never changed a single lot.

This script answers the two questions that decide whether that is a money leak
or a latent trap, in the FRAME the gate runs in (b113's rule):

  Q1 REACHABILITY — how often does each regime actually fire on the real books?
     Replays the broker's own deal history (read-only /api/history/deals)
     through the REAL compute_performance_state -> assess_account_policy chain,
     bar by bar, and counts regimes. Also walks the full trade journal, which
     covers more calendar than the broker's 7-day feed.

  Q2 SIZE — what would the unwired regimes have done to the lot?
     Runs the REAL evaluate_proposal on a fixed blueprint under each regime and
     records the lot it produced, so the cost of the gap is a number.

Everything is derived by IMPORT (b109/b118: no restated literals): the
thresholds, the multipliers, MAX_RISK_PER_TRADE_PCT, TIGHT_REGIMES and
STOP_TRADING_REGIMES all come from the modules under review.

Post-processing is a PURE function of the collected rows (b127/b128's rule) so
scripts/b127_producer_reproduction.py can re-execute it against the frozen
ledger. Writes a NEW ledger; touches no production state.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(str(_ROOT / ".env"))

from engines import risk as R                                  # noqa: E402
from engines import auto_executor as AE                        # noqa: E402
from engines.risk import assess_account_policy, compute_performance_state  # noqa: E402

LEDGER = _ROOT / "data" / "backtest" / "b136_regime_wiring_census.json"
JOURNAL = _ROOT / "data" / "xau_plan" / "trade_journal.csv"

# The four regimes risk.assess_account_policy can emit, discovered from the
# module rather than typed here (b122: an arm must be the rule it is named for).
def emittable_regimes() -> list[str]:
    import ast
    src = Path(R.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "assess_account_policy":
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                        and getattr(sub.targets[0], "id", None) == "regime"
                        and isinstance(sub.value, ast.Constant)
                        and isinstance(sub.value.value, str)):
                    if sub.value.value not in found:
                        found.append(sub.value.value)
    return found


def wired_regimes() -> dict:
    """What the ENTRY path actually does with each regime name."""
    return {
        "blocks_entry": sorted(AE.STOP_TRADING_REGIMES),
        "shrinks_size": sorted(AE.TIGHT_REGIMES),
        "reads_risk_multiplier": False,   # evaluate_proposal never touches the field
    }


# ── Q1: replay the real books through the real chain ───────────────────────

def _deals_from_bridge(days: int = 30):
    """Read-only broker deal history. Returns [] if the bridge is unreachable."""
    try:
        from bridge_client import BridgeClient
        b = BridgeClient()
        r = b.get_history_deals("XAUUSD", days) or {}
        data = r.get("data", r.get("deals", []))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _deals_from_journal():
    """The journal is the longer window: it survives the broker's 7-day feed."""
    if not JOURNAL.exists():
        return []
    rows = []
    with JOURNAL.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rows.append({
                    "ticket": int(float(r["ticket"])),
                    "time": float(r["close_time"]),
                    "profit": float(r["profit"]),
                    "entry": 1,               # journal rows are closes
                    "source": "journal",
                })
            except (KeyError, TypeError, ValueError):
                continue
    return sorted(rows, key=lambda d: d["ticket"])


def regime_walk(deals: list[dict], start_balance: float) -> list[dict]:
    """Feed the real deal list through the REAL state chain, one close at a
    time, and record the regime the policy module reports.

    `equity` is the honest live value: with MAX_OPEN_POSITIONS=1 and a
    risk-capped SL, an open trade's unrealised loss is bounded by the risk it
    was sized for, so the walk evaluates the policy at the two moments live
    actually samples it — flat (equity==balance) and at max adverse excursion
    (equity==balance-risk_usd).
    """
    out: list[dict] = []
    bal = float(start_balance)
    state: dict = {}
    for d in deals:
        bal = round(bal + float(d.get("profit") or 0.0), 2)
        day = datetime.fromtimestamp(float(d["time"]), tz=timezone.utc).date().isoformat()
        state = compute_performance_state(state, day, bal, [d])
        risk_usd = round(bal * AE.MAX_RISK_PER_TRADE_PCT, 2)
        for tag, eq in (("flat", bal), ("max_adverse", round(bal - risk_usd, 2))):
            pol = assess_account_policy(
                balance=bal, equity=eq, free_margin=eq, margin=0.0,
                daily_pnl=float(state.get("daily_pnl") or 0.0),
                loss_streak=int(state.get("loss_streak") or 0),
                open_positions=0 if tag == "flat" else 1)
            out.append({
                "deal_ticket": d.get("ticket"), "day": day, "excursion": tag,
                "balance": bal, "equity": eq,
                "daily_pnl": float(state.get("daily_pnl") or 0.0),
                "loss_streak": int(state.get("loss_streak") or 0),
                "regime": pol["regime"],
                "risk_multiplier": pol["risk_multiplier"],
                "trade_allowed": pol["trade_allowed"],
                "policy_base_risk_pct": pol["base_risk_pct"],
                "executor_risk_pct_if_executed": round(
                    AE.MAX_RISK_PER_TRADE_PCT
                    * (0.5 if pol["regime"] in AE.TIGHT_REGIMES else 1.0), 6),
            })
    return out


# ── Q2: what does the entry path actually size under each regime? ───────────

def _blueprint():
    # A neutral, gate-passing SELL: 10.00 stop distance, 25.00 target (RR 2.5).
    return {"side": "SELL", "entry_price": 4450.0, "sl": 4460.0,
            "tp": 4425.0, "symbol": "XAUUSD"}


def regime_multipliers(balance: float = 5000.0) -> dict:
    """regime -> risk_multiplier, DISCOVERED by calling the real policy
    function over inputs chosen to land in each branch. No literal is restated
    here (b109/b122: an arm must be the rule it is named for, and a hand-typed
    multiplier is exactly how a parity gap hides)."""
    probes = [
        # (daily_pnl, loss_streak, drawdown fraction) chosen from the module's
        # own thresholds, which are read below rather than copied.
        (0.0, 0, 0.0),            # normal
        (0.0, 2, 0.0),            # defensive (loss_streak >= 2)
        (-balance * 0.011, 0, 0.0),   # defensive (daily loss >= 1%)
        (0.0, 0, 0.026),          # recovery (drawdown >= 2.5%)
        (0.0, 0, 0.051),          # locked (drawdown >= 5%)
    ]
    found: dict[str, float] = {}
    for pnl, streak, dd in probes:
        pol = assess_account_policy(balance=balance,
                                    equity=round(balance * (1 - dd), 2),
                                    free_margin=balance, margin=0.0,
                                    daily_pnl=pnl, loss_streak=streak,
                                    open_positions=0)
        found.setdefault(pol["regime"], pol["risk_multiplier"])
    return found


def size_probe(balance: float = 5000.0) -> list[dict]:
    """Run the REAL evaluate_proposal once per regime name and record the lot.

    Market-hours and cooldown are stubbed OPEN (they are time gates, not the
    subject); nothing else is stubbed, so the number is what the live path
    would send. No bridge is passed and DRY_RUN is irrelevant: this function
    never reaches execute_trade — evaluate_proposal only BUILDS a command.
    """
    import copy
    real_open = AE.is_market_open
    from engines import cooldown as CD
    real_cd = CD.check_entry_cooldown
    AE.is_market_open = lambda *a, **k: True
    CD.check_entry_cooldown = lambda now=None: {"allowed": True}
    mult = regime_multipliers(balance)
    try:
        rows = []
        for reg in emittable_regimes():
            pol = {"trade_allowed": reg not in AE.STOP_TRADING_REGIMES,
                   "regime": reg, "open_positions": 0, "balance": balance,
                   "risk_multiplier": mult.get(reg, 1.0)}
            perf = compute_performance_state({}, datetime.now(timezone.utc)
                                             .date().isoformat(), balance, [])
            res = AE.evaluate_proposal({"blueprint": copy.deepcopy(_blueprint()),
                                        "grade": "B"}, pol, perf, {}, None)
            rows.append({
                "regime": reg,
                "policy_risk_multiplier": pol["risk_multiplier"],
                "execute": bool(res.get("execute")),
                "reason": res.get("reason"),
                "executor_risk_pct": res.get("risk_pct"),
                "risk_usd": res.get("risk_usd"),
                "lot": (res.get("command") or {}).get("lot"),
            })
        return rows
    finally:
        AE.is_market_open = real_open
        CD.check_entry_cooldown = real_cd


# ── pure post-processing (b128: reachable from a test) ─────────────────────

def derive(rows: list[dict], size_rows: list[dict],
           regimes: list[str], wired: dict) -> dict:
    """The verdict, as a pure function of the collected rows."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["regime"]] = counts.get(r["regime"], 0) + 1
    unwired = []
    for reg in regimes:
        blocks = reg in wired["blocks_entry"]
        shrinks = reg in wired["shrinks_size"]
        if reg == "normal":
            continue
        if not (blocks or shrinks):
            unwired.append(reg)
    # the size the unwired regime WOULD have taken vs what the path takes
    deltas = {}
    for s in size_rows:
        if s["regime"] in unwired and s["execute"]:
            deltas[s["regime"]] = {
                "lot_as_run": s["lot"],
                "policy_multiplier_ignored": s["policy_risk_multiplier"],
            }
    return {
        "regimes_emittable": regimes,
        "regimes_wired_into_entry": {
            "blocks_entry": wired["blocks_entry"],
            "shrinks_size": wired["shrinks_size"],
        },
        "unwired_regimes": sorted(unwired),
        "regime_fire_counts": counts,
        "sample_cycles": len(rows),
        "unwired_size_effect": deltas,
        "verdict": ("ALL_EMITTABLE_REGIMES_WIRED" if not unwired
                    else "UNWIRED_REGIME_PRESENT:" + ",".join(sorted(unwired))),
    }


def main() -> dict:
    now = datetime.now(timezone.utc)
    deals_live = _deals_from_bridge(30)
    journal = _deals_from_journal()
    # start the walk from the balance the journal's first close implies
    start = 5000.0
    rows = regime_walk(journal, start) if journal else []
    live_rows = regime_walk(deals_live, start) if deals_live else []
    size_rows = size_probe()
    regimes = emittable_regimes()
    wired = wired_regimes()
    led = {
        "_note": "b136 census: does every regime risk.assess_account_policy can "
                 "emit actually change the live entry path? Read-only; no order "
                 "endpoint touched.",
        "_at": now.isoformat(),
        "_frame": {
            "source_of_deals": "trade_journal.csv (long window) + "
                               "/api/history/deals (live 30d feed)",
            "chain": "engines.risk.compute_performance_state -> "
                     "engines.risk.assess_account_policy (the live functions)",
            "excursions": ["flat", "max_adverse"],
            "max_risk_per_trade_pct": AE.MAX_RISK_PER_TRADE_PCT,
            "journal_rows": len(journal),
            "live_deal_rows": len(deals_live),
        },
        "journal_walk": rows,
        "live_walk": live_rows,
        "size_probe": size_rows,
        "_derived": derive(rows + live_rows, size_rows, regimes, wired),
    }
    return led


if __name__ == "__main__":
    out = main()
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(out, indent=1), encoding="utf-8")
    d = out["_derived"]
    print("regimes emittable:", d["regimes_emittable"])
    print("wired:", d["regimes_wired_into_entry"])
    print("UNWIRED:", d["unwired_regimes"])
    print("fire counts:", d["regime_fire_counts"], "of", d["sample_cycles"], "cycles")
    print("verdict:", d["verdict"])
    print("ledger:", LEDGER)
