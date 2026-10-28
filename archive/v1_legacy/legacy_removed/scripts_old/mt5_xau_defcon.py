"""
Closed-Trade Feedback Loop — DEFCON system for trade management adaptation.

The agent learns from its own closed trades:
  1. Snapshot closed deals from MT5
  2. Classify exit types (SL, TP, partial, managed)
  3. Build exit analysis (win rate, SL ratio, PnL per type)
  4. Compute DEFCON level + trading insights
  5. Filter management decisions based on insights
  6. Filter entry decisions based on DEFCON

DEFCON levels:
  - GREEN: All systems go — full runner/scale-in/partial allowed
  - YELLOW: Loss streak >= 2 or high SL ratio with >= 3 closed → disable runners/scale-ins
  - RED: >= 5 closed, SL dominant, AND daily PnL < 0 → no new entries
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

TRADING_DIR = Path("/home/ai/hermes-trading/data/trading")


def _now() -> datetime:
    return datetime.now()


def snapshot_closed_deals(days_back: int = 7) -> list[dict]:
    """Load closed XAUUSD deals from MT5 history. Returns list of deal dicts."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            return []

        from_date = _now() - timedelta(days=days_back)
        # Position history for XAUUSD
        history = mt5.history_deals_get(from_date, _now(), group="XAUUSD")
        if history is None:
            mt5.shutdown()
            return []

        deals = []
        for d in history:
            # Only entry-out deals (closing)
            if d.entry != 1:  # 0=in, 1=out
                deals.append({
                    "ticket": int(d.ticket),
                    "time": int(d.time),
                    "type": "BUY" if d.type == 0 else "SELL",
                    "volume": float(d.volume),
                    "price": float(d.price),
                    "profit": float(d.profit),
                    "commission": float(d.commission),
                    "swap": float(d.swap),
                    "comment": d.comment or "",
                })
        mt5.shutdown()
        return deals

    except Exception:
        return []


def classify_exits(deals: list[dict]) -> list[dict]:
    """Classify closed deals by exit type from comment field."""
    classified = []
    for d in deals:
        comment = d.get("comment", "").lower()
        net_pnl = d.get("profit", 0) + d.get("commission", 0) + d.get("swap", 0)

        # Classify exit type
        if "[sl" in comment or "stop loss" in comment:
            exit_type = "sl"
        elif "[tp" in comment or "take profit" in comment:
            exit_type = "tp"
        elif "hermes manage" in comment or "partial" in comment or "trail" in comment:
            exit_type = "managed"
        elif "manual" in comment or "user" in comment:
            exit_type = "manual"
        else:
            exit_type = "unknown"

        classified.append({
            "ticket": d["ticket"],
            "time": d["time"],
            "type": d["type"],
            "pnl": round(float(net_pnl), 2),
            "exit_type": exit_type,
            "raw_comment": d.get("comment", ""),
        })

    return classified


def analyze_exits(classified: list[dict]) -> dict:
    """Analyze classified exits and produce summary stats."""
    if not classified:
        return {
            "total": 0, "sl_count": 0, "tp_count": 0, "managed_count": 0,
            "sl_ratio": 0.0, "sl_dominant": False,
            "total_pnl": 0.0, "avg_sl_loss": 0.0, "avg_tp_profit": 0.0,
            "managed_total_pnl": 0.0, "managed_win_ratio": 0.0,
        }

    total = len(classified)
    sls = [d for d in classified if d["exit_type"] == "sl"]
    tps = [d for d in classified if d["exit_type"] == "tp"]
    managed = [d for d in classified if d["exit_type"] == "managed"]

    sl_count = len(sls)
    tp_count = len(tps)
    managed_count = len(managed)

    total_pnl = sum(d["pnl"] for d in classified)
    sl_ratio = sl_count / total if total > 0 else 0.0
    sl_dominant = sl_ratio >= 0.5

    avg_sl_loss = sum(d["pnl"] for d in sls) / sl_count if sl_count > 0 else 0.0
    avg_tp_profit = sum(d["pnl"] for d in tps) / tp_count if tp_count > 0 else 0.0

    # Managed exits performance
    managed_total_pnl = sum(d["pnl"] for d in managed)
    managed_wins = [d for d in managed if d["pnl"] > 0]
    managed_win_ratio = len(managed_wins) / managed_count if managed_count > 0 else 0.0

    return {
        "total": total, "sl_count": sl_count, "tp_count": tp_count,
        "managed_count": managed_count,
        "sl_ratio": round(sl_ratio, 3), "sl_dominant": sl_dominant,
        "total_pnl": round(total_pnl, 2),
        "avg_sl_loss": round(avg_sl_loss, 2),
        "avg_tp_profit": round(avg_tp_profit, 2),
        "managed_total_pnl": round(managed_total_pnl, 2),
        "managed_win_ratio": round(managed_win_ratio, 2),
    }


def compute_trading_insights(
    performance_state: dict = None,
    account: dict = None,
) -> dict:
    """
    Compute DEFCON level and trading insights from performance + closed trades.

    Returns:
        {defcon: green|yellow|red,
         runner_allowed: bool,
         scale_in_allowed: bool,
         entry_allowed: bool,
         risk_override: float|None,
         insights: [str]}
    """
    # Default: everything allowed
    result = {
        "defcon": "green",
        "runner_allowed": True,
        "scale_in_allowed": True,
        "entry_allowed": True,
        "risk_override": None,
        "insights": [],
        "timestamp": _now().isoformat(),
    }

    # Get closed deals and analyze
    deals = snapshot_closed_deals(days_back=14)
    exits_cl = classify_exits(deals)
    exits_analysis = analyze_exits(exits_cl)

    total = exits_analysis["total"]
    sl_ratio = exits_analysis["sl_ratio"]
    sl_dominant = exits_analysis["sl_dominant"]

    loss_streak = 0
    daily_pnl = 0.0

    if performance_state:
        loss_streak = int(performance_state.get("loss_streak", 0) or 0)
        daily_pnl = float(performance_state.get("daily_pnl", 0.0) or 0.0)
    elif account:
        daily_pnl = float(account.get("profit", 0.0) or 0.0)

    # ═══ DEFCON: RED — total freeze ═══
    if total >= 5 and sl_dominant and daily_pnl < 0:
        result["defcon"] = "red"
        result["runner_allowed"] = False
        result["scale_in_allowed"] = False
        result["entry_allowed"] = False
        result["risk_override"] = 0.0
        result["insights"].append(
            f"🚨 DEFCON RED: {total} بسته, {sl_ratio:.0%} SL, PnL={daily_pnl:.1f} — ورود جدید ممنوع")
        return result

    # ═══ DEFCON: YELLOW — restrict runners ═══
    if loss_streak >= 2 or (sl_ratio >= 0.5 and total >= 3):
        result["defcon"] = "yellow"
        result["runner_allowed"] = False
        result["scale_in_allowed"] = False
        result["entry_allowed"] = True
        result["risk_override"] = 0.75  # Reduced from 0.5 — allow more trades under YELLOW
        result["insights"].append(
            f"⚠️ DEFCON YELLOW: loss_streak={loss_streak}, SL={sl_ratio:.0%} — رانر و scale-in غیرفعال, ریسک نصف")
    else:
        result["defcon"] = "green"
        if total > 0:
            tp_count = exits_analysis.get("tp_count", 0)
            sl_count_ex = exits_analysis.get("sl_count", 0)
            result["insights"].append(
                f"🟢 DEFCON GREEN: {total} بسته, {tp_count} TP, {sl_count_ex} SL, win={1-sl_ratio:.0%}")

    # ═══ Managed exit check ═══
    mwr = exits_analysis["managed_win_ratio"]
    managed_count = exits_analysis["managed_count"]
    if managed_count >= 3 and mwr <= 0.3:
        result["runner_allowed"] = False
        result["insights"].append(
            f"📉 مدیریت ضعیف: {managed_count} معامله مدیریتی, {mwr:.0%} برنده — رانر غیرفعال")

    return result


def filter_management_by_insights(
    management_decision: dict,
    insights: dict,
) -> dict:
    """
    Filter management decisions through DEFCON insights.
    - trail/scale_in blocked → demote to hold or close_runner
    - partial/be/close_early → always allowed
    - hold → always passes
    """
    action = management_decision.get("action", "hold")
    defcon = insights.get("defcon", "green")

    # Actions always allowed
    if action in ("hold", "move_be", "partial_close", "close_trade_early"):
        return management_decision

    # Trail → if blocked, close runner instead
    if action == "trail" and not insights.get("runner_allowed", True):
        return {
            "action": "close_runner",
            "new_sl": None,
            "new_tp": None,
            "close_pct": 1.0,
            "reason": "DEFCON: رانر غیرفعال — بستن کامل پوزیشن",
            "confidence": 0.8,
        }

    # Scale in → if blocked, hold
    if "scale_in" in action and not insights.get("scale_in_allowed", True):
        return {
            "action": "hold",
            "new_sl": None,
            "new_tp": None,
            "close_pct": None,
            "reason": "DEFCON: scale-in غیرفعال — نگه‌داشتن پوزیشن",
            "confidence": 0.5,
        }

    return management_decision


def filter_entry_by_insights(
    trade_allowed: bool,
    reason: str,
    insights: dict,
) -> dict:
    """
    Filter entry decisions through DEFCON insights.
    Returns {allowed: bool, reason: str, risk_pct_override: float|None}
    """
    defcon = insights.get("defcon", "green")

    if defcon == "red":
        return {"allowed": False, "reason": "DEFCON RED: ورود جدید ممنوع", "risk_pct_override": None}

    if defcon == "yellow":
        return {
            "allowed": trade_allowed,
            "reason": reason + " (DEFCON YELLOW: ریسک نصف)",
            "risk_pct_override": insights.get("risk_override", 0.5),
        }

    return {"allowed": trade_allowed, "reason": reason, "risk_pct_override": None}


# ── Test ──
if __name__ == "__main__":
    print("═══ DEFCON Closed-Trade Feedback ═══")
    deals = snapshot_closed_deals(days_back=14)
    print(f"Closed deals (14 days): {len(deals)}")
    classified = classify_exits(deals)
    analysis = analyze_exits(classified)
    print(json.dumps(analysis, indent=2, default=str))

    insights = compute_trading_insights()
    print(f"\nDEFCON: {insights['defcon']}")
    for i in insights["insights"]:
        print(f"  {i}")
