#!/usr/bin/env python3
"""
HERMES DECISION COLLECTOR (HTTP Bridge Edition)
═══════════════════════════════════════════════

Linux-side: Collects ALL market data from Windows MT5 via HTTP Bridge.
This script = "eyes" — sees everything.
Hermes (me) = "brain" — reads output, decides.
"""

import json
import sys
from datetime import datetime, timezone

# ── Path setup ──
SCRIPTS_DIR = "/home/ai/hermes-trading/scripts"
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from hermes_brain import HermesMT5Bridge

sys.path.insert(0, SCRIPTS_DIR)
from mt5_xau_context import build_plan_context
from mt5_xau_smc import smc_analyse, merge_smc_with_classic


def _now() -> datetime:
    return datetime.now(timezone.utc)


def collect() -> dict:
    """Collect full market analysis for Hermes decision."""
    bridge = HermesMT5Bridge()
    result = bridge.connect()
    
    if not result:
        return {"error": "bridge_connection_failed"}
    
    output = {
        "timestamp": _now().isoformat(),
        "session": None,
        "market": {},
        "account": {},
        "positions": {},
        "analysis": {"classic": {}, "smc": {}, "merged": {}},
        "recommendation": None,
    }
    
    # ── Account ──
    acc = bridge.get_account_info()
    if acc.get("ok"):
        a = acc["data"]
        output["account"] = {
            "login": a.get("login"),
            "balance": a.get("balance"),
            "equity": a.get("equity"),
            "profit": a.get("profit"),
            "margin_level": a.get("margin_level"),
        }
    
    # ── Positions ──
    pos = bridge.get_positions("XAUUSD")
    if pos.get("ok"):
        output["positions"] = {
            "count": pos.get("count", 0),
            "total_profit": sum(p.get("profit", 0) for p in pos.get("data", [])),
            "list": [{
                "ticket": p["ticket"],
                "type": "BUY" if p["type"] == 0 else "SELL",
                "volume": p["volume"],
                "open_price": p["open_price"],
                "current_price": p["price_current"],
                "sl": p["sl"],
                "tp": p["tp"],
                "profit": p["profit"],
                "swap": p["swap"],
            } for p in pos.get("data", [])],
        }
    
    # ── Raw data from bridge ──
    raw = result
    output["market"] = {
        "symbol": "XAUUSD",
        "bid": raw.get("bid"),
        "ask": raw.get("ask"),
        "spread": raw.get("spread"),
        "terms_accepted": raw.get("terms_accepted"),
    }
    
    # ── SL/TP info ──
    sltp = bridge.get_sl_tp_info("XAUUSD")
    if sltp.get("ok"):
        output["market"]["valid_sl_range"] = sltp["data"].get("valid_sl_range")
        output["market"]["valid_tp_range"] = sltp["data"].get("valid_tp_range")
    
    # ── Session ──
    hour = _now().hour
    if 0 <= hour < 7:
        output["session"] = "asia"
    elif 7 <= hour < 13:
        output["session"] = "london"
    else:
        output["session"] = "newyork"
    
    # ── We need M15/H1/H4 data for analysis ──
    # Bridge doesn't provide historical data, so we use simplified analysis
    # In full version, we'd add OHLC endpoints to bridge server
    
    output["recommendation"] = {
        "action": "manual_review_required",
        "reason": "Bridge mode: historical data analysis needs OHLC endpoint. Run visual analysis on MT5.",
        "next_step": "Check MT5 chart + use hermes_master_trader.py for analysis",
    }
    
    return output


def format_for_hermes(collected: dict) -> str:
    """Format as human-readable report for Hermes."""
    now_str = collected.get("timestamp", "now")[:19].replace("T", " ")
    session = collected.get("session", "unknown")
    account = collected.get("account", {})
    positions = collected.get("positions", {})
    market = collected.get("market", {})
    
    lines = [
        "═══════════════════════════════════════════════",
        f"HERMES MARKET SNAPSHOT — {now_str}",
        f"Session: {session.upper()} | Symbol: XAUUSD",
        "═══════════════════════════════════════════════",
        "",
        "👤 ACCOUNT",
        f"  Balance: ${account.get('balance', 'N/A')}",
        f"  Equity:  ${account.get('equity', 'N/A')}",
        f"  Profit:  ${account.get('profit', 'N/A')}",
        f"  Margin:  {account.get('margin_level', 'N/A')}%",
        "",
        "📊 MARKET",
        f"  Bid: {market.get('bid', 'N/A')}",
        f"  Ask: {market.get('ask', 'N/A')}",
        f"  Spread: {market.get('spread', 'N/A')}",
        "",
        f"💼 POSITIONS: {positions.get('count', 0)} open",
    ]
    
    for pos in positions.get("list", []):
        lines.append(f"  {'BUY' if pos['type']==0 else 'SELL'} #{pos['ticket']}: {pos['volume']} lot @ {pos['open_price']} | P/L: ${pos['profit']:.2f} | SL:{pos['sl']} TP:{pos['tp']}")
    
    lines.append("")
    
    rec = collected.get("recommendation", {})
    lines.append("🤖 SYSTEM")
    lines.append(f"  Action: {rec.get('action', 'unknown')}")
    lines.append(f"  Note: {rec.get('reason', 'N/A')}")
    
    return "\n".join(lines)


if __name__ == "__main__":
    data = collect()
    print(format_for_hermes(data))
    print("\n--- JSON ---")
    print(json.dumps(data, indent=2, ensure_ascii=False))
