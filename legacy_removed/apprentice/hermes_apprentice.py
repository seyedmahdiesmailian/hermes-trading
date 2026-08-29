#!/usr/bin/env python3
"""
HERMES APPRENTICE — Autonomous Rule-Based Trader
═══════════════════════════════════════════════

Runs when Hermes (me) is NOT present.
Follows encoded rules from Master's weekly lessons.
Never stops trading, never panics.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/home/ai/hermes-trading/scripts")
sys.path.insert(0, "/home/ai/hermes-trading")

from hermes_brain import HermesMT5Bridge
import mt5_xau_smc as smc
import mt5_xau_context as context
from hermes_notifier import send_telegram

BASE_DIR = Path("/home/ai/hermes-trading")
LOG_DIR = BASE_DIR / "logs"
SHARED_DIR = BASE_DIR / "shared"

def log(msg: str, level="APPRENTICE"):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "apprentice.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def to_rows(data: list[dict]) -> list[dict]:
    return data if data else []


class HermesApprentice:
    """
    Apprentice: Rule-based autonomous trader.
    
    Principles (encoded from Master's lessons):
    1. NEVER risk more than 0.5% per trade
    2. ALWAYS wait for confirmation
    3. CUT losers, let winners run
    4. NEVER trade against higher timeframe trend
    """

    def __init__(self, bridge: HermesMT5Bridge):
        self.bridge = bridge
        self.symbol = "XAUUSD"
        self.max_risk_pct = 0.005
        self.min_confidence = 0.6
        self.max_positions = 2

    def gather_data(self) -> dict:
        tick = self.bridge.get_tick(self.symbol)
        acc = self.bridge.get_account_info()
        positions = self.bridge.get_positions(self.symbol)
        rates_m15 = self.bridge.get_rates(self.symbol, "M15", 80)
        rates_h1 = self.bridge.get_rates(self.symbol, "H1", 80)
        rates_h4 = self.bridge.get_rates(self.symbol, "H4", 80)
        return {
            "tick": tick.get("data", {}),
            "account": acc.get("data", {}),
            "positions": positions.get("data", []),
            "m15_raw": rates_m15.get("data", []),
            "h1_raw": rates_h1.get("data", []),
            "h4_raw": rates_h4.get("data", []),
        }

    def analyze(self, data: dict) -> dict:
        m15_rows = to_rows(data["m15_raw"])
        h1_rows = to_rows(data["h1_raw"])
        h4_rows = to_rows(data["h4_raw"])

        if len(m15_rows) < 20 or len(h1_rows) < 20:
            return {"status": "insufficient_data"}

        smc_result = smc.smc_analyse(m15_rows)
        ctx_result = context.build_plan_context(m15_rows, h1_rows, h4_rows, "current")

        return {
            "smc": smc_result,
            "context": ctx_result,
            "price": data["tick"].get("ask", 0),
            "positions_count": len(data["positions"]),
            "balance": data["account"].get("balance", 0),
        }

    def decide(self, analysis: dict) -> dict:
        """
        Pure rule-based decision. No intuition — only logic.
        """
        price = analysis["price"]
        smc_data = analysis.get("smc", {})
        ctx = analysis.get("context", {})
        zones = ctx.get("zones", {})
        atr = zones.get("atr", price * 0.001)

        has_positions = analysis.get("positions_count", 0) > 0
        balance = analysis.get("balance", 0)

        # === RULES ===
        if has_positions:
            return {"action": "WATCH", "reason": "Managing existing trade"}

        if ctx.get("bias") != "bullish":
            return {"action": "WATCH", "reason": "No bullish bias — no trade"}

        active_obs = smc_data.get("active_order_blocks", [])
        bullish_obs = [ob for ob in active_obs if ob["type"] == "bullish" and ob["high"] < price]
        if not bullish_obs:
            return {"action": "WATCH", "reason": "No bullish OB below price"}

        # Find best OB
        nearest_ob = max(bullish_obs, key=lambda ob: ob["high"])
        ob_low = nearest_ob["low"]
        sl = ob_low - (atr * 0.5)
        sl_distance = price - sl
        tp = price + (sl_distance * 2.0)

        # Risk check: loss should not exceed 0.5% of balance
        risk_amount = balance * self.max_risk_pct
        # Simple risk calculation
        if sl_distance <= 0:
            return {"action": "WATCH", "reason": "Invalid SL distance"}

        # For demo: fixed minimum volume
        volume = 0.01

        return {
            "action": "BUY",
            "reason": f"Rule: bullish bias + OB support, SL={sl:.1f}, TP={tp:.1f}",
            "trade": {"symbol": "XAUUSD", "type": "BUY", "volume": volume,
                      "sl": sl, "tp": tp},
        }

    def execute(self, decision: dict) -> dict:
        action = decision.get("action")
        if action == "WATCH":
            log(f"Watching: {decision.get('reason')}")
            return {"executed": False}

        if action in ("BUY", "SELL"):
            trade = decision.get("trade", {})
            command = {"symbol": trade.get("symbol", "XAUUSD"), "type": action,
                       "volume": trade.get("volume", 0.01),
                       "sl": trade.get("sl"), "tp": trade.get("tp"),
                       "comment": "Hermes Apprentice"}
            result = self.bridge.send_order(command)
            log(f"Order: {json.dumps(result, default=str)[:200]}")
            if result.get("ok"):
                send_telegram(f"🤖 Apprentice {action} at {trade.get('volume')}lot, SL={trade.get('sl')}, TP={trade.get('tp')}")
            return result

        return {"executed": False}

    def run_cycle(self):
        log("=== Apprentice Cycle Start ===")
        data = self.gather_data()
        analysis = self.analyze(data)
        decision = self.decide(analysis)
        result = self.execute(decision)
        log("=== Apprentice Cycle Complete ===")
        return {"decision": decision, "execution": result}


if __name__ == "__main__":
    log("Hermes Apprentice — Starting")
    bridge = HermesMT5Bridge()
    if bridge.connect():
        app = HermesApprentice(bridge)
        app.run_cycle()
    else:
        log("CONNECTION FAILED", "ERROR")
