"""
Advanced Trade Management — rules for managing open positions.

A professional trader doesn't just enter and set SL/TP. They manage:
  1. Breakeven (BE) — move SL to entry once trade is profitable
  2. Trailing Stop — lock in profits as price moves in favor
  3. Partial TP — close part at R1, let rest run
  4. Time-based exit — close if not hitting TP within N bars
  5. News lock — tighten SL or close before high-impact events

All functions take position dict + current market data, return action dict.
"""
from typing import Optional
from datetime import datetime


# Default BE rules (can be tuned by learning)
DEFAULT_BE_RULES = {
    "be_at_r": 0.5,           # Move to BE when profit = 0.5R (half risk)
    "be_offset_pips": 0.1,    # BE offset: 0.1 pips above entry (cover spread)
    "trail_after_r": 1.0,     # Start trailing after 1R profit
    "trail_distance_atr": 0.5, # Trail distance = 0.5 ATR
    "partial_at_r": 1.5,      # Close 50% at 1.5R
    "partial_pct": 0.5,       # Percentage to close at partial TP
    "time_exit_bars": 16,     # Exit if no TP after 16 M15 bars (4 hours)
    "time_exit_min_r": 0.2,   # Min R before time exit activates
    "news_tighten_r": 0.3,    # If news within 1h, tighten SL to 0.3R
}

def evaluate_trade_management(
    position: dict,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    current_price: float,
    atr: float,
    risk_usd: float,
    open_bars: int,
    news_risk: dict = None,
    be_rules: dict = None,
    current_risk_multiplier: float = 1.0,
) -> dict:
    """
    Evaluate what management action to take for an open position.

    Priority order (highest first):
      1. News lock — tighten SL before high-impact event (safety)
      2. Time exit — too long without hitting TP (safety)
      3. Partial TP — take profit at target R (profit taking)
      4. Trailing stop — lock in profits (profit locking)
      5. BE — move SL to entry (risk reduction)

    Args:
        position: open position dict from MT5 (has 'type': BUY|SELL, 'profit': USD)
        entry_price: original entry price
        sl_price: current stop loss price
        tp_price: current take profit price
        current_price: current bid (for buy) or ask (for sell)
        atr: current ATR in price units
        risk_usd: original risk in USD
        open_bars: number of M15 bars since entry
        news_risk: news risk dict from calendar
        be_rules: override default BE rules
        current_risk_multiplier: current risk multiplier

    Returns action dict.
    """
    rules = {**DEFAULT_BE_RULES, **(be_rules or {})}

    is_buy = position.get("type") == "BUY"
    current_pnl = position.get("profit", 0.0)

    # Current R multiple
    risk_amount = risk_usd if risk_usd > 0 else 1.0
    current_r = current_pnl / risk_amount if risk_amount > 0 else 0

    pip_value = 0.01  # XAUUSD pip

    def _be_needed():
        """Check if BE move is needed (SL not at entry yet)."""
        if current_r < rules["be_at_r"] or sl_price <= 0:
            return False, None
        be_sl = entry_price + (rules["be_offset_pips"] * pip_value) if is_buy else entry_price - (rules["be_offset_pips"] * pip_value)
        needs = (is_buy and sl_price < be_sl) or (not is_buy and sl_price > be_sl)
        return needs, round(be_sl, 2) if needs else None

    def _trail_needed():
        """Check if trailing stop should fire."""
        if current_r < rules["trail_after_r"]:
            return False, None
        trail_dist = atr * rules["trail_distance_atr"]
        trail_sl = (current_price - trail_dist) if is_buy else (current_price + trail_dist)
        moves_up = is_buy and trail_sl > sl_price + 0.01
        moves_down = not is_buy and trail_sl < sl_price - 0.01
        return (moves_up or moves_down), round(trail_sl, 2)

    def _partial_needed():
        """Check if partial TP should fire."""
        if current_r < rules["partial_at_r"] or rules["partial_pct"] <= 0:
            return False
        return True

    def _time_exit_needed():
        """Check if time-based exit should fire."""
        if open_bars < rules["time_exit_bars"]:
            return False
        return True

    def _news_lock_needed():
        """Check if news lock should fire."""
        if not (news_risk and news_risk.get("risk_active") and current_r > 0):
            return False, None
        tighten_dist = rules["news_tighten_r"] * risk_usd  # $$ — need price conversion
        # Convert risk dollars to price: sl_dist = risk / lot / 100
        # Simplified: use entry ± tight fraction of atr
        news_sl = entry_price + (rules["news_tighten_r"] * atr) if is_buy else entry_price - (rules["news_tighten_r"] * atr)
        should_tighten = (is_buy and news_sl > sl_price) or (not is_buy and news_sl < sl_price)
        return should_tighten, round(news_sl, 2) if should_tighten else None

    # Check in priority order — return highest priority action
    # 1. News lock (safety first)
    needs, new_sl = _news_lock_needed()
    if needs:
        return {
            "action": "news_lock", "new_sl": new_sl, "new_tp": tp_price,
            "close_pct": None, "confidence": 0.85,
            "reason": f"قفل خبری — {news_risk.get('next_event', '?')} در {news_risk.get('hours_until', '?')}h",
        }

    # 2. Time exit
    if _time_exit_needed():
        label = f"سود={current_r:.2f}R" if current_r >= rules["time_exit_min_r"] else f"ضرر={current_r:.2f}R"
        return {
            "action": "time_exit", "new_sl": None, "new_tp": None,
            "close_pct": 1.0, "confidence": 0.75,
            "reason": f"خروج زمانی — {open_bars} بار باز، {label}",
        }

    # 3. Partial TP (take profit)
    if _partial_needed():
        return {
            "action": "partial_close", "new_sl": sl_price, "new_tp": tp_price,
            "close_pct": rules["partial_pct"], "confidence": 0.85,
            "reason": f"بستن {rules['partial_pct']*100:.0f}% پوزیشن در R={current_r:.2f}",
        }

    # 4. Trailing stop (lock profits)
    needs, new_sl = _trail_needed()
    if needs:
        trail_dist = atr * rules["trail_distance_atr"]
        return {
            "action": "trail", "new_sl": new_sl, "new_tp": tp_price,
            "close_pct": None, "confidence": 0.8,
            "reason": f"Trailing stop — SL به {new_sl:.2f} (ATR×{rules['trail_distance_atr']}={trail_dist:.2f})",
        }

    # 5. BE (risk reduction — lowest priority of active actions)
    needs, new_sl = _be_needed()
    if needs:
        return {
            "action": "move_be", "new_sl": new_sl, "new_tp": tp_price,
            "close_pct": None, "confidence": 0.9,
            "reason": f"SL به نقطه ورود منتقل شد (BE) — R فعلی={current_r:.2f} ≥ {rules['be_at_r']}",
        }

    # Default: hold
    return {
        "action": "hold", "new_sl": None, "new_tp": None,
        "close_pct": None, "confidence": 0.5,
        "reason": "پوزیشن در حالت عادی",
    }


def get_sl_tp_blueprint(
    entry: float,
    direction: str,
    atr: float,
    regime: str = "range",
    risk_usd: float = 10.0,
    account_balance: float = 1338.71,
    risk_multiplier: float = 1.0,
) -> dict:
    """
    Generate SL/TP blueprint for a new trade.

    Rules:
    - SL = 1.5 ATR (min) to 2.0 ATR (max) based on regime
    - TP = 2R (min) to 3R (max) based on regime
    - In range: tighter SL, wider TP (mean reversion)
    - In trend: wider SL, standard TP (trend following)
    """
    is_buy = direction.lower() in ("buy", "long", "bullish")

    # SL distance
    if regime == "trend":
        sl_atr_mult = 1.8
        tp_rr = 2.5
    elif regime == "range":
        sl_atr_mult = 1.2
        tp_rr = 3.0  # Wider TP in range (mean reversion)
    else:
        sl_atr_mult = 1.5
        tp_rr = 2.0

    sl_dist = atr * sl_atr_mult
    if is_buy:
        sl_price = entry - sl_dist
        tp_price = entry + (sl_dist * tp_rr)
    else:
        sl_price = entry + sl_dist
        tp_price = entry - (sl_dist * tp_rr)

    # Convert to points for MT5
    point = 0.01
    sl_points = round(sl_dist / point)
    tp_points = round((sl_dist * tp_rr) / point)

    # Position sizing
    effective_risk = risk_usd * risk_multiplier
    lot = round(effective_risk / sl_dist, 2)
    lot = max(0.01, min(lot, 2.0))  # Cap at 2.0 lots

    # Check margin
    margin_required = lot * entry * 0.01  # ~1% of contract value
    max_margin = account_balance * 0.5  # Max 50% of balance
    if margin_required > max_margin:
        lot = round(max_margin / (entry * 0.01), 2)
        lot = max(0.01, lot)

    return {
        "sl_price": round(sl_price, 2),
        "tp_price": round(tp_price, 2),
        "sl_points": sl_points,
        "tp_points": tp_points,
        "lot": lot,
        "risk_usd": round(lot * sl_dist, 2),
        "risk_atr_mult": sl_atr_mult,
        "tp_rr": tp_rr,
        "margin_required": round(margin_required, 2),
    }


# Quick test
if __name__ == "__main__":
    # Test BE rule
    pos = {"type": "BUY", "profit": 5.0}
    action = evaluate_trade_management(
        position=pos,
        entry_price=4300.0, sl_price=4298.0, tp_price=4306.0,
        current_price=4303.0, atr=7.0, risk_usd=10.0, open_bars=5,
    )
    print(f"BE test: {action['action']} — {action['reason']}")

    # Test blueprint
    bp = get_sl_tp_blueprint(entry=4300.0, direction="buy", atr=7.0, regime="range")
    print(f"Blueprint: SL={bp['sl_price']} TP={bp['tp_price']} lot={bp['lot']} risk=${bp['risk_usd']}")
