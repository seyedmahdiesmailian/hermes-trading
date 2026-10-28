"""
Divergence Detection — RSI divergence with price on multiple timeframes.

RSI divergence is one of the strongest reversal signals in technical analysis.
  - Bullish divergence: Price makes lower low, RSI makes higher low → reversal UP
  - Bearish divergence: Price makes higher high, RSI makes lower high → reversal DOWN
  - Hidden divergence: continuation signals (price trend vs RSI trend)

Professionals use this to:
  1. Confirm entries (M5 divergence + M15 structure)
  2. Catch reversals early (M5 divergence before M15 signal)
  3. Avoid fake breakouts (price breaks but RSI doesn't confirm)
"""

from typing import Optional


def calc_rsi(close_prices: list[float], period: int = 14) -> list[float]:
    """Calculate RSI for a series of closing prices."""
    if len(close_prices) < period + 1:
        return []

    gains, losses = [], []
    for i in range(1, len(close_prices)):
        diff = close_prices[i] - close_prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsi = []
    # First value
    rs = avg_gain / avg_loss if avg_loss != 0 else 100
    rsi.append(100 - (100 / (1 + rs)))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        rsi.append(100 - (100 / (1 + rs)))

    return rsi


def _find_swings(data: list[float], window: int = 3) -> list[dict]:
    """Find swing highs and lows in a series. Returns list of {index, value, type}."""
    if len(data) < window * 2 + 1:
        return []
    swings = []
    for i in range(window, len(data) - window):
        left = data[i - window:i]
        right = data[i + 1:i + window + 1]
        val = data[i]
        if all(val > l for l in left) and all(val > r for r in right):
            swings.append({"index": i, "value": float(val), "type": "high"})
        elif all(val < l for l in left) and all(val < r for r in right):
            swings.append({"index": i, "value": float(val), "type": "low"})
    return swings


def detect_divergence(
    price_rows: list[dict],
    rsi_period: int = 14,
    lookback_bars: int = 50,
    swing_window: int = 3,
) -> dict:
    """
    Detect RSI divergence on a set of OHLC bars.

    Args:
        price_rows: list of {open, high, low, close} dicts
        rsi_period: RSI period (default 14)
        lookback_bars: how many recent bars to analyze
        swing_window: swing detection window size

    Returns:
        {found: bool, type: bullish|bearish|hidden_bullish|hidden_bearish|none,
         confidence: 0-1, price: [swing info], rsi: [swing info], description: str}
    """
    closes = [r["close"] for r in price_rows[-lookback_bars:]]
    if len(closes) < rsi_period + 10:
        return {"found": False, "type": "none", "confidence": 0.0,
                "description": "داده کافی برای divergence نیست"}

    rsi_vals = calc_rsi(closes, rsi_period)
    if not rsi_vals or len(rsi_vals) < 10:
        return {"found": False, "type": "none", "confidence": 0.0}

    # Align: RSI has fewer values than prices
    price_aligned = closes[-len(rsi_vals):]

    # Find swings in price and RSI
    price_swings = _find_swings(price_aligned, swing_window)
    rsi_swings = _find_swings(rsi_vals, swing_window)

    if len(price_swings) < 2 or len(rsi_swings) < 2:
        return {"found": False, "type": "none", "confidence": 0.0,
                "description": "swing کافی شناسایی نشد"}

    # Get most recent 2 swings of each type
    recent_price_lows = [s for s in price_swings[-4:] if s["type"] == "low"]
    recent_price_highs = [s for s in price_swings[-4:] if s["type"] == "high"]
    recent_rsi_lows = [s for s in rsi_swings[-4:] if s["type"] == "low"]
    recent_rsi_highs = [s for s in rsi_swings[-4:] if s["type"] == "high"]

    result = {"found": False, "type": "none", "confidence": 0.0, "description": ""}

    # ═══ Bullish Divergence: Price ↓↓ but RSI ↑↑ ═══
    if len(recent_price_lows) >= 2 and len(recent_rsi_lows) >= 2:
        p1, p2 = recent_price_lows[-2], recent_price_lows[-1]
        r1, r2 = recent_rsi_lows[-2], recent_rsi_lows[-1]

        # Price made lower low, RSI made higher low
        if p2["value"] < p1["value"] and r2["value"] > r1["value"]:
            confidence = min(0.9, 0.5 + (r2["value"] - r1["value"]) / 20)
            result = {
                "found": True, "type": "bullish", "confidence": round(confidence, 2),
                "price_low1": p1["value"], "price_low2": p2["value"],
                "rsi_low1": r1["value"], "rsi_low2": r2["value"],
                "description": f"Bullish divergence: قیمت کف پایینتر ولی RSI کف بالاتر — احتمال برگشت صعودی",
            }
            return result

    # ═══ Bearish Divergence: Price ↑↑ but RSI ↓↓ ═══
    if len(recent_price_highs) >= 2 and len(recent_rsi_highs) >= 2:
        p1, p2 = recent_price_highs[-2], recent_price_highs[-1]
        r1, r2 = recent_rsi_highs[-2], recent_rsi_highs[-1]

        if p2["value"] > p1["value"] and r2["value"] < r1["value"]:
            confidence = min(0.9, 0.5 + (r1["value"] - r2["value"]) / 20)
            result = {
                "found": True, "type": "bearish", "confidence": round(confidence, 2),
                "price_high1": p1["value"], "price_high2": p2["value"],
                "rsi_high1": r1["value"], "rsi_high2": r2["value"],
                "description": f"Bearish divergence: قیمت سقف بالاتر ولی RSI سقف پایینتر — احتمال برگشت نزولی",
            }
            return result

    # ═══ Hidden Bullish: Price ↑↑, RSI ↓↓ (continuation) ═══
    if len(recent_price_lows) >= 2 and len(recent_rsi_lows) >= 2:
        p1, p2 = recent_price_lows[-2], recent_price_lows[-1]
        r1, r2 = recent_rsi_lows[-2], recent_rsi_lows[-1]
        if p2["value"] > p1["value"] and r2["value"] < r1["value"]:
            result = {
                "found": True, "type": "hidden_bullish", "confidence": 0.65,
                "description": "Hidden bullish — تداوم روند صعودی",
            }
            return result

    # ═══ Hidden Bearish: Price ↓↓, RSI ↑↑ (continuation) ═══
    if len(recent_price_highs) >= 2 and len(recent_rsi_highs) >= 2:
        p1, p2 = recent_price_highs[-2], recent_price_highs[-1]
        r1, r2 = recent_rsi_highs[-2], recent_rsi_highs[-1]
        if p2["value"] < p1["value"] and r2["value"] > r1["value"]:
            result = {
                "found": True, "type": "hidden_bearish", "confidence": 0.65,
                "description": "Hidden bearish — تداوم روند نزولی",
            }
            return result

    result["description"] = "divergence تشخیص داده نشد"
    return result


def multi_tf_divergence(
    m5_rows: list[dict],
    m15_rows: list[dict],
    h1_rows: list[dict],
) -> dict:
    """
    Check divergence across multiple timeframes.
    Multi-TF divergence is stronger than single-TF.

    Returns:
        {m5: {}, m15: {}, h1: {}, confluence: bool, confluence_detail: str}
    """
    m5_div = detect_divergence(m5_rows) if m5_rows else {"found": False, "type": "none"}
    m15_div = detect_divergence(m15_rows) if m15_rows else {"found": False, "type": "none"}
    h1_div = detect_divergence(h1_rows, lookback_bars=80) if h1_rows else {"found": False, "type": "none"}

    # Check confluence
    divs = [m for m in [m5_div, m15_div, h1_div] if m.get("found")]
    types = [d["type"] for d in divs]
    all_same = len(divs) >= 2 and all(t == types[0] for t in types)

    confluence = all_same
    detail = ""
    if confluence:
        direction = "صعودی" if "bullish" in types[0] else "نزولی"
        tfs = " + ".join(["M5" if m5_div.get("found") else "",
                          "M15" if m15_div.get("found") else "",
                          "H1" if h1_div.get("found") else ""]).strip(" +")
        detail = f"هم‌گرایی {direction} در {tfs} تایید شد — سیگنال قوی"
    elif len(divs) == 1:
        detail = f"divergence فقط در یک تایم‌فریم — سیگنال متوسط"

    return {
        "m5": m5_div,
        "m15": m15_div,
        "h1": h1_div,
        "confluence": confluence,
        "confluence_detail": detail,
        "signal_strength": "strong" if confluence else "medium" if divs else "none",
    }


# ── Test ──
if __name__ == "__main__":
    import json, sys
    sys.path.insert(0, ".")
    from mt5_xau_decision_collector import _collect_raw_data

    raw = _collect_raw_data()
    if raw.get("mt5_connected"):
        m5_rows = raw.get("m5", [])
        m15_rows = raw.get("m15", [])
        h1_rows = raw.get("h1", [])

        print("═══ Divergence Detection ═══")
        results = multi_tf_divergence(m5_rows, m15_rows, h1_rows)
        for tf in ["m5", "m15", "h1"]:
            d = results[tf]
            status = f"{d['type']} (conf={d['confidence']:.2f})" if d.get("found") else "none"
            print(f"  {tf.upper()}: {status}")
        print(f"\n  Confluence: {results['confluence']}")
        print(f"  Signal: {results['signal_strength']}")
        if results["confluence_detail"]:
            print(f"  Detail: {results['confluence_detail']}")
    else:
        print("MT5 not connected")
