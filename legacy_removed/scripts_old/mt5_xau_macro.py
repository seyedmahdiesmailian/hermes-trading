"""
XAUUSD Macro Context Module — dollar strength, risk sentiment, intermarket.

Synthetic DXY:
  Built from 6 USD pairs weighted like real DXY: EURUSD (57.6%), USDJPY (13.6%),
  GBPUSD (11.9%), USDCAD (9.1%), USDCHF (3.6%), AUDUSD (4.2%). Normalized to ±100.

Risk Sentiment: SPXUSD direction (risk-on/off gauge for gold).
Gold Proxy: XAGUSD correlation (silver leads gold in intraday moves).

Tick Volume: actual tick count on current bar for breakout confirmation.

Higher Timeframes (H4, D1, W1): OHLC + SMC structure for multi-timeframe alignment.
"""
from __future__ import annotations

import numpy as np
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

# DXY weights (Federal Reserve trade-weighted basket, normalized)
DXY_PAIRS = {
    "EURUSD": {"weight": 0.576, "inverse": True},   # EUR up → USD down
    "USDJPY": {"weight": 0.136, "inverse": False},   # USD up → USDJPY up
    "GBPUSD": {"weight": 0.119, "inverse": True},    # GBP up → USD down
    "USDCAD": {"weight": 0.091, "inverse": False},   # USD up → USDCAD up
    "USDCHF": {"weight": 0.036, "inverse": False},   # USD up → USDCHF up
    "AUDUSD": {"weight": 0.042, "inverse": True},    # AUD up → USD down
}

def _pct_change(recent: float, earlier: float) -> float:
    """Percentage change from earlier to recent."""
    if earlier == 0:
        return 0.0
    return ((recent - earlier) / earlier) * 100

def compute_synthetic_dxy(mt5_obj, bars_back: int = 10) -> dict:
    """
    Build synthetic DXY from USD pairs. Returns:
      {dxy_value, dxy_change_pct, dxy_direction, dxy_strength, pair_details}
    """
    result = {"dxy_value": 0.0, "dxy_change_pct": 0.0, "dxy_direction": "flat",
              "dxy_strength": "neutral", "pair_details": {}}

    weighted_sum = 0.0
    weighted_change = 0.0
    total_weight = 0.0

    for pair, cfg in DXY_PAIRS.items():
        try:
            bars = mt5_obj.copy_rates_from_pos(pair, mt5_obj.TIMEFRAME_M15, 0, bars_back + 1)
            if bars is None or len(bars) < 2:
                result["pair_details"][pair] = {"available": False}
                continue

            current = float(bars[-1]["close"])
            prev = float(bars[0]["close"])
            change_pct = _pct_change(current, prev)

            # USD pairs: if inverse (DXY up when pair down), flip sign
            dxy_component = -change_pct if cfg["inverse"] else change_pct

            weighted_sum += dxy_component * cfg["weight"]
            weighted_change += abs(dxy_component) * cfg["weight"]
            total_weight += cfg["weight"]

            result["pair_details"][pair] = {
                "current": current, "change_pct": round(change_pct, 3),
                "dxy_component": round(dxy_component, 3)
            }
        except Exception as e:
            result["pair_details"][pair] = {"available": False, "error": str(e)}

    if total_weight > 0:
        result["dxy_value"] = round(weighted_sum / total_weight, 3)
        result["dxy_change_pct"] = result["dxy_value"]

        if result["dxy_value"] > 0.1:
            result["dxy_direction"] = "up"
            result["dxy_strength"] = "strong" if result["dxy_value"] > 0.3 else "moderate"
        elif result["dxy_value"] < -0.1:
            result["dxy_direction"] = "down"
            result["dxy_strength"] = "strong" if result["dxy_value"] < -0.3 else "moderate"
        else:
            result["dxy_direction"] = "flat"
            result["dxy_strength"] = "neutral"

    return result

def get_risk_sentiment(mt5_obj, bars_back: int = 10) -> dict:
    """
    Read SPXUSD (S&P 500) as risk-on/off gauge.
    SPX up = risk-on = gold can sell off.
    SPX down = risk-off = gold can rally.
    """
    result = {"spx_change_pct": 0.0, "risk_mode": "neutral", "available": False}
    try:
        bars = mt5_obj.copy_rates_from_pos("SPXUSD", mt5_obj.TIMEFRAME_M15, 0, bars_back + 1)
        if bars is None or len(bars) < 2:
            return result

        current = float(bars[-1]["close"])
        prev = float(bars[0]["close"])
        change = _pct_change(current, prev)

        result["available"] = True
        result["spx_change_pct"] = round(change, 3)
        result["spx_value"] = current

        if change > 0.1:
            result["risk_mode"] = "risk_on"
        elif change < -0.1:
            result["risk_mode"] = "risk_off"
        else:
            result["risk_mode"] = "neutral"

    except Exception:
        pass

    return result

def get_silver_correlation(mt5_obj, bars_back: int = 10) -> dict:
    """
    XAGUSD often leads XAUUSD on intraday moves.
    Return direction and magnitude of silver move.
    """
    result = {"xag_change_pct": 0.0, "xag_direction": "flat", "available": False}
    try:
        bars = mt5_obj.copy_rates_from_pos("XAGUSD", mt5_obj.TIMEFRAME_M15, 0, bars_back + 1)
        if bars is None or len(bars) < 2:
            return result

        current = float(bars[-1]["close"])
        prev = float(bars[0]["close"])
        change = _pct_change(current, prev)

        result["available"] = True
        result["xag_value"] = current
        result["xag_change_pct"] = round(change, 3)

        if change > 0.15:
            result["xag_direction"] = "up"
        elif change < -0.15:
            result["xag_direction"] = "down"
        else:
            result["xag_direction"] = "flat"

        result["bullish_for_gold"] = result["xag_direction"] == "up"
        result["bearish_for_gold"] = result["xag_direction"] == "down"

    except Exception:
        pass

    return result

def get_tick_volume(mt5_obj) -> dict:
    """
    Read current M15 bar tick count for breakout confirmation.
    Compare against average volume of last N bars.
    """
    result = {"current_ticks": 0, "avg_ticks": 0, "volume_ratio": 0.0,
              "is_high_volume": False, "available": False}
    try:
        bars = mt5_obj.copy_rates_from_pos("XAUUSD", mt5_obj.TIMEFRAME_M15, 0, 20)
        if bars is None or len(bars) < 5:
            return result

        # Current bar (index -1) tick volume
        current_ticks = int(bars[-1]["tick_volume"])
        # Average of previous bars (excluding current)
        prev_ticks = [int(b["tick_volume"]) for b in bars[:-1] if int(b["tick_volume"]) > 0]
        avg_ticks = np.mean(prev_ticks) if prev_ticks else current_ticks

        result["available"] = True
        result["current_ticks"] = current_ticks
        result["avg_ticks"] = round(float(avg_ticks), 1)
        result["volume_ratio"] = round(current_ticks / avg_ticks, 2) if avg_ticks > 0 else 1.0
        result["is_high_volume"] = result["volume_ratio"] > 1.5

    except Exception:
        pass

    return result

def get_higher_timeframe_context(mt5_obj) -> dict:
    """
    Read H4, D1, W1 OHLC for XAUUSD. Provide:
      - Trend direction on each TF
      - Current bar position within range (premium/discount)
      - Multi-timeframe alignment check
    """
    result = {"h4": {}, "d1": {}, "w1": {}, "alignment": "mixed", "available": False}
    tfs = {
        "h4": mt5_obj.TIMEFRAME_H4,
        "d1": mt5_obj.TIMEFRAME_D1,
        "w1": mt5_obj.TIMEFRAME_W1,
    }

    tf_data = {}
    for tf_name, tf_const in tfs.items():
        try:
            bars = mt5_obj.copy_rates_from_pos("XAUUSD", tf_const, 0, 20)
            if bars is None or len(bars) < 5:
                continue

            closes = [float(b["close"]) for b in bars]
            current = closes[-1]
            high_20 = max(float(b["high"]) for b in bars)
            low_20 = min(float(b["low"]) for b in bars)
            range_20 = high_20 - low_20

            # Trend: compare SMA(5) vs SMA(10)
            sma5 = np.mean(closes[-5:]) if len(closes) >= 5 else current
            sma10 = np.mean(closes[-10:]) if len(closes) >= 10 else current
            ema5 = closes[-1] * (2/6) + (np.mean(closes[-5:-1]) if len(closes) >= 6 else closes[-2]) * (4/6)

            if current > sma10 * 1.001:
                trend = "bullish"
            elif current < sma10 * 0.999:
                trend = "bearish"
            else:
                trend = "neutral"

            # Premium/Discount position
            if range_20 > 0:
                pos_in_range = (current - low_20) / range_20
                if pos_in_range > 0.7:
                    zone = "premium"
                elif pos_in_range < 0.3:
                    zone = "discount"
                else:
                    zone = "equilibrium"
            else:
                pos_in_range = 0.5
                zone = "equilibrium"

            tf_data[tf_name] = {
                "price": current, "trend": trend,
                "high_20": high_20, "low_20": low_20,
                "zone": zone, "pos_in_range": round(pos_in_range, 2),
                "sma10": round(float(sma10), 2),
            }
        except Exception:
            pass

    result.update(tf_data)
    result["available"] = len(tf_data) >= 2

    # Alignment check
    trends = [d.get("trend") for d in tf_data.values()]
    if all(t == "bullish" for t in trends):
        result["alignment"] = "bullish_all"
    elif all(t == "bearish" for t in trends):
        result["alignment"] = "bearish_all"
    elif "bullish" in trends and "bearish" in trends:
        result["alignment"] = "conflicting"
    else:
        result["alignment"] = "mixed"

    # Anti-gold signals
    result["dxy_bearish_4_gold"] = False  # DXY down = gold up
    result["risk_on_bearish_4_gold"] = False  # Risk-on = gold may sell

    return result

def build_macro_snapshot(mt5_obj) -> dict:
    """
    Full macro snapshot: DXY proxy + risk sentiment + silver + volume + higher TFs.
    Call this from the decision collector.
    """
    return {
        "dxy": compute_synthetic_dxy(mt5_obj),
        "risk_sentiment": get_risk_sentiment(mt5_obj),
        "silver": get_silver_correlation(mt5_obj),
        "tick_volume": get_tick_volume(mt5_obj),
        "higher_tf": get_higher_timeframe_context(mt5_obj),
        "timestamp": datetime.now().isoformat(),
    }

# Quick test
if __name__ == "__main__":
    import MetaTrader5 as mt5
    if not mt5.initialize():
        print("MT5 init failed")
        exit(1)

    snap = build_macro_snapshot(mt5)
    import json
    print(json.dumps(snap, indent=2, default=str))
    mt5.shutdown()
