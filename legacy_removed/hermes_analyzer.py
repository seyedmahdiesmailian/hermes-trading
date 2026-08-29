#!/usr/bin/env python3
"""
HERMES ANALYZER — Light Version
═══════════════════════════════════════════════

Simple market analysis using OHLC data from Bridge.
Returns: signal, bias, confidence, DEFCON level.

When Hermes is AWAKE → I read report and approve manually.
When Hermes is ASLEEP → Apprentice logs signal, waits for approval.
"""

from datetime import datetime, timezone


def log(msg):
    print(f"[ANALYZER] {msg}")


def calc_atr(rows: list, period: int = 14) -> float:
    """Average True Range."""
    if len(rows) < 2:
        return 0.5
    trs = []
    for i in range(1, min(period + 1, len(rows))):
        high = rows[i]["high"]
        low = rows[i]["low"]
        prev_close = rows[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.5


def classify_trend(rows: list) -> str:
    """Bullish / Bearish / Neutral based on HH/HL vs LH/LL."""
    if len(rows) < 10:
        return "neutral"
    closes = [r["close"] for r in rows[-20:]]
    highs = [r["high"] for r in rows[-20:]]
    lows = [r["low"] for r in rows[-20:]]

    hh = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i - 1])
    hl = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i - 1])
    lh = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i - 1])
    ll = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i - 1])

    bullish_score = hh + hl
    bearish_score = lh + ll

    if bullish_score > bearish_score + 3:
        return "bullish"
    elif bearish_score > bullish_score + 3:
        return "bearish"
    return "neutral"


def detect_fvg(rows: list) -> list:
    """Detect Fair Value Gaps (3-candle imbalance)."""
    gaps = []
    for i in range(1, len(rows) - 1):
        c1 = rows[i - 1]
        c2 = rows[i]     # gap candle
        c3 = rows[i + 1]
        # Bullish FVG: c1.high < c3.low
        if c3["low"] > c1["high"]:
            gaps.append({"type": "bullish", "top": c3["low"], "bottom": c1["high"], "idx": i})
        # Bearish FVG: c3.high < c1.low
        if c3["high"] < c1["low"]:
            gaps.append({"type": "bearish", "top": c1["low"], "bottom": c3["high"], "idx": i})
    return gaps


def find_nearest_fvg(price: float, fgvs: list) -> dict:
    """Find closest FVG to current price."""
    best = None
    best_dist = float('inf')
    for gap in fgvs:
        mid = (gap["top"] + gap["bottom"]) / 2
        dist = abs(price - mid)
        if dist < best_dist:
            best_dist = dist
            best = gap
    return best


def defcon_level(bias: str, atr: float, confidence: int) -> dict:
    """DEFCON risk system. Lower number = more aggressive (smaller risk)."""
    if bias == "neutral" or confidence < 50:
        return {"level": 5, "risk_pct": 0.5, "sl_mult": 2.0, "max_lot": 0.01, "state": "WAIT"}
    if confidence >= 80:
        return {"level": 3, "risk_pct": 1.5, "sl_mult": 1.5, "max_lot": 0.03, "state": "ACTIVE"}
    if confidence >= 65:
        return {"level": 3, "risk_pct": 1.0, "sl_mult": 1.5, "max_lot": 0.02, "state": "ACTIVE"}
    return {"level": 4, "risk_pct": 0.5, "sl_mult": 2.0, "max_lot": 0.01, "state": "CAUTION"}


def analyze(ohlc_m15: list, ohlc_h1: list, current_price: float) -> dict:
    """Main analysis function."""

    # --- Step 1: Trend on both timeframes ---
    trend_m15 = classify_trend(ohlc_m15)
    trend_h1 = classify_trend(ohlc_h1)

    # --- Step 2: ATR for volatility ---
    atr_m15 = calc_atr(ohlc_m15, 14)

    # --- Step 3: FVG detection ---
    fgvs = detect_fvg(ohlc_m15[-30:])
    nearest_gap = find_nearest_fvg(current_price, fgvs)

    # --- Step 4: Multi-timeframe bias ---
    if trend_m15 == trend_h1 and trend_m15 != "neutral":
        bias = trend_m15
        confidence = 75
    elif trend_m15 != "neutral":
        bias = trend_m15
        confidence = 55
    elif trend_h1 != "neutral":
        bias = trend_h1
        confidence = 50
    else:
        bias = "neutral"
        confidence = 30

    # --- Step 5: FVG boost ---
    if nearest_gap and nearest_gap["type"] == bias and abs(current_price - (nearest_gap["top"] + nearest_gap["bottom"]) / 2) < atr_m15 * 2:
        confidence += 15

    # Cap
    confidence = min(95, max(10, confidence))

    # --- Step 6: DEFCON ---
    defcon = defcon_level(bias, atr_m15, confidence)

    # --- Step 7: Action ---
    if defcon["state"] == "WAIT":
        action = "wait"
    elif bias == "bullish":
        action = "buy"
    elif bias == "bearish":
        action = "sell"
    else:
        action = "wait"

    # --- Step 8: Trade params ---
    sl = 0
    tp = 0
    if action in ["buy", "sell"]:
        direction = 1 if action == "buy" else -1
        sl = round(current_price - atr_m15 * defcon["sl_mult"] * direction, 2)
        tp = round(current_price + atr_m15 * defcon["sl_mult"] * 2 * direction, 2)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bias": bias,
        "confidence": confidence,
        "defcon": defcon,
        "action": action,
        "trend_m15": trend_m15,
        "trend_h1": trend_h1,
        "atr": round(atr_m15, 2),
        "fvg_nearby": nearest_gap is not None,
        "suggested_sl": sl,
        "suggested_tp": tp,
        "risk_pct": defcon["risk_pct"],
        "max_lot": defcon["max_lot"],
    }
