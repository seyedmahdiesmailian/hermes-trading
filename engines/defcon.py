"""DEFCON — closed-trade feedback loop (migrated from legacy mt5_xau_defcon.py).

Legacy source: Hermes_Full_Backup_20260813 skills/trading/autonomous-trading-agent-design
→ references/closed-trade-feedback-loop.md + architecture-v5-modules.md

Pipeline:
    snapshot_closed_deals(days) → classify_exits(deals) → analyze_exits(...)
        → compute_insights(performance, classified) → DEFCON level
        → filter_entry_by_insights()  (wired in auto_executor)
        → filter_management_by_insights()  (wired in trade_management)

DEFCON levels (legacy rules, kept identical):
    GREEN  — default; all actions allowed, full risk
    YELLOW — loss_streak >= 2 OR (sl_ratio >= 0.5 AND closed >= 3)
             → half risk, runners disabled, scale-ins disabled
    RED    — closed >= 5 AND sl_dominant AND daily_pnl < 0
             → no new entries, manage existing only

Legacy key insight kept: managed exits that consistently lose money
(managed_win_ratio <= 0.3 AND managed_total_pnl < 0) → disable runners
even if DEFCON is still green.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def classify_exit(comment: str, profit: float) -> str:
    """Classify a closed deal by its exit type from the MT5 comment field.

    Legacy rules: '[sl ...]' → sl, '[tp ...]' → tp,
    'Hermes manage/partial/trail/early' → managed, else unknown.
    """
    c = (comment or "").lower()
    if c.startswith("[sl") or "[sl" in c:
        return "sl"
    if c.startswith("[tp") or "[tp" in c:
        return "tp"
    if any(k in c for k in ("manage", "partial", "trail", "hermesclose", "hermes manage")):
        return "managed"
    # fallback: profit sign tells little, but unflagged SL-like big losses
    return "unknown"


def classify_exits(deals: list[dict]) -> list[dict]:
    """Attach exit_type to each closed deal (entry deals filtered upstream)."""
    out = []
    for d in deals:
        profit = float(d.get("profit", 0) or 0)
        out.append({
            "ticket": d.get("ticket"),
            "profit": profit,
            "exit_type": classify_exit(str(d.get("comment", "")), profit),
            "side": d.get("side"),
        })
    return out


def analyze_exits(classified: list[dict]) -> dict:
    """Aggregate exit statistics."""
    total = len(classified)
    if total == 0:
        return {"total": 0}
    n_sl = sum(1 for c in classified if c["exit_type"] == "sl")
    n_tp = sum(1 for c in classified if c["exit_type"] == "tp")
    n_managed = [c for c in classified if c["exit_type"] == "managed"]
    m_wins = [c for c in n_managed if c["profit"] > 0]
    m_pnl = sum(c["profit"] for c in n_managed)
    sl_ratio = n_sl / total if total else 0.0
    return {
        "total": total,
        "sl_count": n_sl,
        "tp_count": n_tp,
        "managed_count": len(n_managed),
        "managed_win_ratio": round(len(m_wins) / len(n_managed), 3) if n_managed else None,
        "managed_total_pnl": round(m_pnl, 2),
        "sl_ratio": round(sl_ratio, 3),
        "sl_dominant": sl_ratio >= 0.5,
    }


def compute_insights(
    loss_streak: int = 0,
    daily_pnl: float = 0.0,
    balance: float = 0.0,
    classified: Optional[list[dict]] = None,
) -> dict:
    """Compute DEFCON + allowed actions. Mirrors legacy mt5_xau_defcon.py."""
    stats = analyze_exits(classified or [])
    total = stats.get("total", 0)

    # RED: enough recent trades, SL-dominated, and losing day
    if total >= 5 and stats.get("sl_dominant") and daily_pnl < 0:
        defcon = "RED"
    # YELLOW: 2+ straight losses, or half the closed trades died at SL
    elif loss_streak >= 2 or (stats.get("sl_ratio", 0) >= 0.5 and total >= 3):
        defcon = "YELLOW"
    else:
        defcon = "GREEN"

    insights = {
        "defcon": defcon,
        "risk_override": None,
        "trade_allowed": True,
        "runner_allowed": True,
        "scale_in_allowed": True,
        "exit_stats": stats,
    }

    if defcon == "YELLOW":
        insights["risk_override"] = 0.5          # half risk
        insights["runner_allowed"] = False       # no trailing runners
        insights["scale_in_allowed"] = False     # no pyramid adds
    elif defcon == "RED":
        insights["risk_override"] = 0.0
        insights["trade_allowed"] = False        # manage existing only

    # Legacy rule: failing managed-exit strategy → disable runners regardless of DEFCON
    _mwr = stats.get("managed_win_ratio")
    if (
        stats.get("managed_count", 0) >= 3
        and _mwr is not None and _mwr <= 0.3
        and (stats.get("managed_total_pnl") or 0) < 0
    ):
        insights["runner_allowed"] = False
        insights["runner_blocked_reason"] = "managed_exits_losing"

    return insights


def filter_entry_by_insights(allowed: bool, reason: Optional[str], insights: Optional[dict]) -> dict:
    """Legacy entry filter: block RED, apply risk_override from YELLOW."""
    if insights is None:
        return {"allowed": allowed, "risk_pct_override": None, "reason": reason}
    if not allowed:
        return {"allowed": False, "risk_pct_override": None, "reason": reason}
    if not insights.get("trade_allowed", True):
        return {
            "allowed": False,
            "risk_pct_override": None,
            "reason": f"defcon_{insights.get('defcon', 'red').lower()}:entry_blocked",
        }
    return {"allowed": True, "risk_pct_override": insights.get("risk_override"), "reason": None}


def filter_management_by_insights(management: dict, insights: Optional[dict]) -> dict:
    """Legacy management filter: safety valves pass; runners/scale-ins obey DEFCON."""
    if insights is None:
        return management
    action = management.get("action", "hold")
    if action == "hold":
        return management
    if action in {"close_trade_early", "partial_take_profit", "move_stop_to_breakeven"}:
        return management  # safety/profit actions always allowed
    if not insights.get("runner_allowed", True) and action in {"trail_stop", "close_runner"}:
        return {
            "action": "close_runner",
            "close_fraction": 1.0,
            "reason": f"insights:defcon_{insights.get('defcon')}:runner_blocked",
        }
    if not insights.get("scale_in_allowed", True) and str(action).startswith("scale_in"):
        return {"action": "hold", "reason": f"insights:defcon_{insights.get('defcon')}:scale_in_blocked"}
    return management
