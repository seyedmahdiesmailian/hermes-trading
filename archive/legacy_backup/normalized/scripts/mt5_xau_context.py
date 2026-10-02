from __future__ import annotations

from statistics import mean


def compute_value_zone(rows: list[dict]) -> tuple[float, float]:
    highs = sorted([r["high"] for r in rows])
    lows = sorted([r["low"] for r in rows])
    n = len(highs)
    # Use 10th and 90th percentiles — much tighter than raw min/max
    p10 = int(n * 0.10)
    p90 = int(n * 0.90) - 1
    range_low = lows[p10] if p10 < n else lows[0]
    range_high = highs[p90] if p90 < n else highs[-1]
    width = range_high - range_low
    return range_low + (width * 0.25), range_low + (width * 0.75)


def classify_bias(rows: list[dict], min_move: float = 2.0, min_agreement: int = 3) -> str:
    closes = [r["close"] for r in rows[-5:]]
    if len(closes) < 5:
        return "neutral"
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    up_count = sum(1 for d in diffs if d > 0)
    down_count = sum(1 for d in diffs if d < 0)
    net_move = closes[-1] - closes[0]
    if net_move >= min_move and up_count >= min_agreement:
        return "bullish"
    if net_move <= -min_move and down_count >= min_agreement:
        return "bearish"
    return "neutral"


def estimate_atr(rows: list[dict]) -> float:
    ranges = [r["high"] - r["low"] for r in rows[-14:]]
    return mean(ranges) if ranges else 0.0


def derive_trade_zones(value_low: float, value_high: float, atr: float) -> dict:
    half = atr * 0.5
    return {
        "value_low": value_low,
        "value_high": value_high,
        "long_entry_low": value_low - half,
        "long_entry_high": value_low,
        "short_entry_low": value_high,
        "short_entry_high": value_high + half,
    }


def _alignment_label(m15_bias: str, h1_bias: str, h4_bias: str) -> str:
    votes = [m15_bias, h1_bias, h4_bias]
    directional = [v for v in votes if v in {"bullish", "bearish"}]
    if len(directional) >= 2 and len(set(directional)) == 1:
        return "aligned"
    if directional:
        return "mixed"
    return "neutral"


def _distance_in_atr(price: float, level: float, atr: float) -> float:
    if atr <= 0:
        return 0.0
    return abs(price - level) / atr


def _detect_regime(
    bias: str,
    alignment: str,
    trend_strength: float,
    last_price: float,
    value_low: float,
    value_high: float,
    atr: float,
    m15_bias: str,
    h1_bias: str,
    h4_bias: str,
) -> str:
    strong_trend = trend_strength >= max(atr * 0.35, 3.0)
    higher_tf_aligned = h1_bias == h4_bias and h1_bias in {"bullish", "bearish"}
    pullback_alignment = higher_tf_aligned and m15_bias not in {h1_bias, "neutral"}

    if bias == "neutral" or not strong_trend:
        return "range"

    if not (alignment == "aligned" or pullback_alignment or higher_tf_aligned):
        return "range"

    if bias == "bullish":
        if last_price > value_high + (atr * 0.25):
            return "breakout_continuation"
        return "pullback_continuation"
    if last_price < value_low - (atr * 0.25):
        return "breakout_continuation"
    return "pullback_continuation"


def _build_execution_plan(bias: str, zones: dict, atr: float, regime: str) -> dict:
    if regime == "range":
        # Range: use value zone edges as targets (mean reversion)
        return {
            "entry_mode": "mean_reversion_wait",
            "scale_in_levels": [],
            "tp_levels": [
                round(zones["value_low"], 2),
                round(zones["value_high"], 2),
            ],
            "tp_shares": [0.5, 0.5],
            "breakout_trigger": round(zones["value_high"] + atr * 0.2, 2),
            "pullback_trigger": round(zones["value_low"], 2),
        }

    if bias == "bullish":
        scale_levels = [round(zones["long_entry_high"], 2), round(max(zones["long_entry_low"], zones["long_entry_high"] - (atr * 0.3)), 2)]
        breakout_trigger = round(zones["value_high"] + (atr * 0.1), 2)
        if regime == "breakout_continuation":
            base_target = max(zones["short_entry_high"], breakout_trigger)
            tp_levels = [
                round(base_target + (atr * 0.5), 2),
                round(base_target + atr, 2),
                round(base_target + (atr * 2.0), 2),
            ]
        else:
            tp_levels = [
                round(zones["short_entry_low"], 2),
                round(zones["short_entry_high"], 2),
                round(zones["short_entry_high"] + atr, 2),
            ]
    else:
        scale_levels = [round(zones["short_entry_low"], 2), round(min(zones["short_entry_high"], zones["short_entry_low"] + (atr * 0.3)), 2)]
        breakout_trigger = round(zones["value_low"] - (atr * 0.1), 2)
        if regime == "breakout_continuation":
            base_target = min(zones["long_entry_low"], breakout_trigger)
            tp_levels = [
                round(base_target - (atr * 0.5), 2),
                round(base_target - atr, 2),
                round(base_target - (atr * 2.0), 2),
            ]
        else:
            tp_levels = [
                round(zones["long_entry_high"], 2),
                round(zones["long_entry_low"], 2),
                round(zones["long_entry_low"] - atr, 2),
            ]

    if regime == "breakout_continuation":
        entry_mode = "breakout_pullback_hybrid"
    else:
        entry_mode = "scale_in_pullback"

    return {
        "entry_mode": entry_mode,
        "scale_in_levels": scale_levels,
        "tp_levels": tp_levels,
        "tp_shares": [0.5, 0.3, 0.2],
        "breakout_trigger": breakout_trigger,
        "pullback_trigger": scale_levels[0] if scale_levels else None,
    }


def build_plan_context(m15_rows: list[dict], h1_rows: list[dict], h4_rows: list[dict], session_name: str) -> dict:
    value_low, value_high = compute_value_zone(h1_rows)
    atr = estimate_atr(m15_rows)
    m15_bias = classify_bias(m15_rows)
    h1_bias = classify_bias(h1_rows)
    h4_bias = classify_bias(h4_rows)
    bias = h4_bias if h4_bias != "neutral" else h1_bias
    if bias == "neutral":
        bias = m15_bias
    zones = derive_trade_zones(value_low=value_low, value_high=value_high, atr=atr)
    last_price = m15_rows[-1]["close"]
    trend_strength = round(abs(h4_rows[-1]["close"] - h4_rows[-5]["close"]), 2)
    alignment = _alignment_label(m15_bias, h1_bias, h4_bias)
    regime = _detect_regime(
        bias=bias,
        alignment=alignment,
        trend_strength=trend_strength,
        last_price=last_price,
        value_low=zones["value_low"],
        value_high=zones["value_high"],
        atr=atr,
        m15_bias=m15_bias,
        h1_bias=h1_bias,
        h4_bias=h4_bias,
    )
    if regime == "range":
        bias = "neutral"
    execution = _build_execution_plan(bias=bias, zones=zones, atr=atr, regime=regime)
    quality = {
        "trend_strength": trend_strength,
        "alignment": alignment,
        "distance_to_value_low_atr": round(_distance_in_atr(last_price, zones["value_low"], atr), 2),
        "distance_to_value_high_atr": round(_distance_in_atr(last_price, zones["value_high"], atr), 2),
        "bias_votes": {"m15": m15_bias, "h1": h1_bias, "h4": h4_bias},
        "regime": regime,
    }
    if bias == "bullish":
        invalidation = zones["long_entry_low"] - (atr * 0.25)
        targets = execution["tp_levels"] or [zones["short_entry_low"], zones["short_entry_high"]]
    elif bias == "bearish":
        invalidation = zones["short_entry_high"] + (atr * 0.25)
        targets = execution["tp_levels"] or [zones["long_entry_high"], zones["long_entry_low"]]
    else:
        invalidation = zones["long_entry_low"] - (atr * 0.25)
        targets = []
    return {
        "symbol": "XAUUSD",
        "session": session_name,
        "bias": bias,
        "atr": atr,
        "zones": zones,
        "invalidation": invalidation,
        "targets": targets,
        "quality": quality,
        "execution": execution,
        "context": {
            "m15_last": last_price,
            "h1_last": h1_rows[-1]["close"],
            "h4_last": h4_rows[-1]["close"],
        },
    }
