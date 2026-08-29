#!/usr/bin/env python3
"""
HERMES MASTER — Senior Trader
═══════════════════════════════════════════════

Architecture:
  1. Get market data via HTTP Bridge (from Windows MT5)
  2. Run old analysis engines (SMC + Context + DEFCON)
  3. Hermes decides based on analysis
  4. Execute via Bridge
  5. Notify via Telegram
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
import mt5_xau_defcon as defcon
from hermes_notifier import send_telegram, notify_trade_opened, notify_analysis

BASE_DIR = Path("/home/ai/hermes-trading")
LOG_DIR = BASE_DIR / "logs"

def log(msg: str, level="MASTER"):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "master.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def to_rows(data: list[dict]) -> list[dict]:
    return data if data else []


class HermesMasterTrader:
    def __init__(self, bridge: HermesMT5Bridge):
        self.bridge = bridge
        self.symbol = "XAUUSD"

    def gather_data(self) -> dict:
        log("Gathering market data...")
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
        log("Running analysis engines...")
        m15_rows = to_rows(data["m15_raw"])
        h1_rows = to_rows(data["h1_raw"])
        h4_rows = to_rows(data["h4_raw"])

        if len(m15_rows) < 20 or len(h1_rows) < 20:
            log("Insufficient data for analysis", "WARN")
            return {"status": "insufficient_data"}

        smc_result = smc.smc_analyse(m15_rows)
        ctx_result = context.build_plan_context(m15_rows, h1_rows, h4_rows, "current")

        deals = []
        for p in data["positions"]:
            deals.append({"ticket": p.get("ticket"), "symbol": p.get("symbol"),
                          "type": 0 if p.get("type") == "BUY" else 1,
                          "volume": p.get("volume", 0), "price": p.get("price_open", 0),
                          "profit": p.get("profit", 0), "time": 0})
        insights = defcon.compute_trading_insights(deals)

        return {"smc": smc_result, "context": ctx_result, "defcon": insights,
                "price": data["tick"].get("ask", 0), "positions_count": len(data["positions"]),
                "balance": data["account"].get("balance", 0)}

    def decide(self, analysis: dict) -> dict:
        log("Hermes analyzing...")
        price = analysis["price"]
        smc_data = analysis.get("smc", {})
        ctx = analysis.get("context", {})
        zones = ctx.get("zones", {})
        atr = zones.get("atr", price * 0.001)
        smc_phase = smc_data.get("structure", {}).get("phase", "range")
        smc_direction = smc_data.get("overall_direction", "neutral")
        active_obs = smc_data.get("active_order_blocks", [])
        has_positions = analysis.get("positions_count", 0) > 0

        log(f"State: bias={ctx.get('bias','NEUTRAL')}, regime={ctx.get('regime','unknown')}, SMC={smc_phase}/{smc_direction}")
        log(f"Price: {price}, ATR: {atr}, Active OBs: {len(active_obs)}, Has positions: {has_positions}")

        # Send analysis notification
        notify_analysis(
            smc_signal=f"{smc_phase}/{smc_direction}",
            context_bias=ctx.get("bias", "NEUTRAL"),
            decision="Analyzing...",
            price=price
        )

        # === TRADING LOGIC ===
        if has_positions:
            return {"action": "WATCH", "reason": "Already in position"}

        if ctx.get("bias") == "bullish" and len(active_obs) > 0:
            nearest_ob = None
            for ob in active_obs:
                if ob["type"] == "bullish" and ob["high"] < price:
                    if nearest_ob is None or ob["high"] > nearest_ob["high"]:
                        nearest_ob = ob

            if nearest_ob:
                ob_low = nearest_ob["low"]
                sl = ob_low - (atr * 0.5)
                sl_distance = price - sl
                tp = price + (sl_distance * 2.0)
                volume = 0.01

                return {
                    "action": "BUY",
                    "reason": f"Bullish + OB at {((ob_low+nearest_ob['high'])/2):.2f}",
                    "trade": {"symbol": "XAUUSD", "type": "BUY", "volume": volume,
                              "sl": sl, "tp": tp},
                }

        return {"action": "WATCH", "reason": "No valid setup"}

    def execute(self, decision: dict) -> dict:
        action = decision.get("action")
        if action == "WATCH":
            log("No execution — observing")
            return {"executed": False}

        if action in ("BUY", "SELL"):
            trade = decision.get("trade", {})
            command = {"symbol": trade.get("symbol", "XAUUSD"), "type": action,
                       "volume": trade.get("volume", 0.01),
                       "sl": trade.get("sl"), "tp": trade.get("tp"),
                       "comment": "Hermes Master"}
            result = self.bridge.send_order(command)
            log(f"Order result: {json.dumps(result, default=str)[:200]}")

            if result.get("ok"):
                data = result.get("data", {})
                notify_trade_opened(
                    symbol=trade["symbol"], direction=action,
                    volume=trade["volume"], price=data.get("price", 0),
                    sl=trade.get("sl", 0), tp=trade.get("tp", 0),
                    ticket=data.get("ticket", 0)
                )
            return result

        return {"executed": False, "reason": "unknown_action"}

    def run_cycle(self):
        log("=== Master Cycle Start ===")
        data = self.gather_data()
        analysis = self.analyze(data)
        decision = self.decide(analysis)
        result = self.execute(decision)
        log("=== Master Cycle Complete ===")
        return {"analysis": analysis, "decision": decision, "execution": result}


if __name__ == "__main__":
    log("Hermes Master Trader — Starting")
    bridge = HermesMT5Bridge()
    if bridge.connect():
        trader = HermesMasterTrader(bridge)
        trader.run_cycle()
    else:
        log("CONNECTION FAILED", "ERROR")
