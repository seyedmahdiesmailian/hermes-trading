#!/usr/bin/env python3
"""
HERMES FULL ORCHESTRATOR
═══════════════════════════════════════════════

Master = Hermes (me) when online
Apprentice = Rule-based when I'm away

Switch logic:
  - if HermesMaster process running → Master mode (wait for me to decide)
  - else → Apprentice mode (auto-trade 24/7)
"""

import json, sys, time, os
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/home/ai/hermes-trading")
sys.path.insert(0, "/home/ai/hermes-trading/scripts")

from hermes_brain import HermesMT5Bridge
from hermes_notifier import notify_trade_opened, notify_trade_closed, notify_analysis, notify_cron_report, notify_error, send_telegram

BASE_DIR = Path("/home/ai/hermes-trading")

def log(msg: str, level="ORCH"):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


def is_hermes_online() -> bool:
    """Check if Hermes Master is running interactively."""
    # For now: check if there's an active tty session or if a flag file exists
    flag_file = BASE_DIR / ".hermes_online"
    if flag_file.exists():
        # Check if stale (older than 5 minutes)
        mtime = flag_file.stat().st_mtime
        return (time.time() - mtime) < 300
    return False


def detect_regime(price: float, h1_rows: list, h4_rows: list) -> str:
    """Detect market regime."""
    if len(h1_rows) < 30 or len(h4_rows) < 20:
        return "unknown"
    h1_close = [r["close"] for r in h1_rows[-20:]]
    h4_close = [r["close"] for r in h4_rows[-10:]]
    h1_sma = sum(h1_close) / len(h1_close)
    h4_sma = sum(h4_close) / len(h4_close)
    if price > h1_sma and price > h4_sma:
        return "uptrend"
    if price < h1_sma and price < h4_sma:
        return "downtrend"
    return "ranging"


def run_master_cycle(bridge: HermesMT5Bridge):
    """Hermes (me) runs — I make the decisions."""
    log("MODE: MASTER (Hermes is online)")
    send_telegram("🧠 <b>Hermes Master</b> is now online and active!")
    
    import mt5_xau_smc as smc
    import mt5_xau_context as context_module
    import mt5_xau_defcon as defcon

    tick = bridge.get_tick("XAUUSD")
    price = tick.get("data", {}).get("ask", 0)
    positions = bridge.get_positions("XAUUSD")
    has_pos = positions.get("count", 0) > 0

    log(f"Price: {price}, Positions: {has_pos}")

    if has_pos:
        log("Already in position — monitoring")
        notify_analysis(price, "monitoring", "N/A", "HOLD - Monitoring open position")
        return {"action": "WATCH", "reason": "position_open"}

    # Get data for analysis
    m15 = bridge.get_rates("XAUUSD", "M15", 80).get("data", [])
    h1 = bridge.get_rates("XAUUSD", "H1", 80).get("data", [])
    h4 = bridge.get_rates("XAUUSD", "H4", 80).get("data", [])

    # Run engines
    try:
        smc_result = smc.smc_analyse(m15)
        ctx = context_module.build_plan_context(m15, h1, h4, "current")
        bias = ctx.get("bias", "NEUTRAL")
        zones = ctx.get("zones", {})
        atr = zones.get("atr", price * 0.001)
    except Exception as e:
        log(f"Analysis error: {e}", "ERROR")
        return {"action": "ERROR", "reason": str(e)}

    # Build market context
    regime = detect_regime(price, h1, h4)
    active_obs = smc_result.get("active_order_blocks", [])
    
    notify_analysis(
        price=price,
        bias=bias,
        smc=f"{smc_result.get('structure',{}).get('phase','range')}/{smc_result.get('overall_direction','neutral')}",
        decision=f"Regime: {regime}, OBs: {len(active_obs)}"
    )

    return {
        "action": "ANALYZED",
        "data": {
            "price": price,
            "bias": bias,
            "regime": regime,
            "smc": smc_result,
            "atr": atr,
            "active_obs": len(active_obs)
        },
        "reason": "Hermes is analyzing — awaiting decision"
    }


def run_apprentice_cycle(bridge: HermesMT5Bridge):
    """Apprentice runs — rule-based auto-trading."""
    log("MODE: APPRENTICE (Hermes is away)")

    import mt5_xau_smc as smc
    import mt5_xau_context as context_module

    tick = bridge.get_tick("XAUUSD")
    price = tick.get("data", {}).get("ask", 0)
    positions = bridge.get_positions("XAUUSD")
    has_pos = positions.get("count", 0) > 0

    # Gather data
    m15 = bridge.get_rates("XAUUSD", "M15", 80).get("data", [])
    h1 = bridge.get_rates("XAUUSD", "H1", 80).get("data", [])
    h4 = bridge.get_rates("XAUUSD", "H4", 80).get("data", [])

    if len(m15) < 20 or len(h1) < 20:
        log("Insufficient data")
        return {"action": "SKIP"}

    # Run analysis
    smc_result = smc.smc_analyse(m15)
    ctx = context_module.build_plan_context(m15, h1, h4, "current")
    bias = ctx.get("bias", "NEUTRAL")
    zones = ctx.get("zones", {})
    atr = zones.get("atr", price * 0.001)

    # === APPRENTICE RULES ===
    
    if has_pos:
        # Check if position reached BE or has significant DD — could add logic
        return {"action": "WATCH", "reason": "Holding position"}

    # Only trade bullish setups (simpler, conservative)
    if bias != "bullish":
        return {"action": "WATCH", "reason": f"No bullish bias ({bias})"}

    active_obs = [ob for ob in smc_result.get("active_order_blocks", []) 
                  if ob["type"] == "bullish" and ob["high"] < price]
    if not active_obs:
        return {"action": "WATCH", "reason": "No bullish OB support"}

    # Choose best OB
    nearest_ob = max(active_obs, key=lambda ob: ob["high"])
    ob_low = nearest_ob["low"]
    sl = ob_low - (atr * 0.5)
    sl_dist = price - sl
    if sl_dist <= 0:
        return {"action": "WATCH", "reason": "Invalid SL"}
    tp = price + (sl_dist * 2.0)
    volume = 0.01  # Demo minimum

    # Execute trade
    # Execute trade ONLY if explicitly enabled
    DRY_RUN = True  # ← SAFE MODE: Set to False when ready to trade live
    
    if DRY_RUN:
        log(f"[DRY RUN] Would open: BUY @ {price}, SL={sl:.2f}, TP={tp:.2f}")
        send_telegram(f"📊 <b>Analysis Signal</b>\n\n"
                      f"Would enter: BUY {volume} lot\n"
                      f"Entry: {price:.2f}\n"
                      f"SL: {sl:.2f}\n"
                      f"TP: {tp:.2f}\n"
                      f"\n<i>Reply with /trade to execute</i>")
        return {"action": "SIGNAL", "reason": "dry_run", "price": price, "sl": sl, "tp": tp}

    result = bridge.send_order({
        "symbol": "XAUUSD", "type": "BUY", "volume": volume,
        "sl": sl, "tp": tp, "comment": "Hermes Apprentice"
    })

    if result.get("ok"):
        data = result.get("data", {})
        ticket = data.get("ticket")
        notify_trade_opened("XAUUSD", "BUY", volume, data.get("price", price), sl, tp, ticket)
        log(f"Apprentice OPENED trade #{ticket}")
        return {"action": "BUY", "ticket": ticket}
    else:
        notify_error(f"Apprentice trade failed: {result.get('error')}")
        return {"action": "ERROR", "reason": result.get("error", "unknown")}


def main():
    send_telegram("🤖 <b>Hermes Trading System</b> started!")
    
    bridge = HermesMT5Bridge()
    if not bridge.connect():
        msg = "❌ FAILED to connect to MT5 Bridge"
        log(msg, "FATAL")
        notify_error(msg)
        return 1

    acc = bridge.get_account_info()
    balance = acc.get("data", {}).get("balance", 0)
    log(f"Connected. Balance: ${balance}")
    send_telegram(f"✅ Connected to MT5\n💰 Balance: ${balance}")

    # Detect mode
    hermes_online = is_hermes_online()
    positions = bridge.get_positions("XAUUSD")
    
    if hermes_online:
        result = run_master_cycle(bridge)
    else:
        result = run_apprentice_cycle(bridge)

    # Final cron report
    pos_count = bridge.get_positions("XAUUSD").get("count", 0)
    final_balance = bridge.get_account_info().get("data", {}).get("balance", balance)
    
    mode = "MASTER" if hermes_online else "APPPRENTICE"
    notify_cron_report(mode, pos_count, final_balance)
    
    log(f"Cycle done. Mode: {mode}, Action: {result.get('action')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
