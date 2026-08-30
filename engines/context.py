from __future__ import annotations

from statistics import mean

# Entry-zone lookback in bars (M5). A/B 2026-08-30 (scripts/ab_zone_width.py)
# on 13×500-bar M5 windows: 8/12/20 bars → see finding in backlog.
ZONE_LOOKBACK = 12



def estimate_atr(rows: list[dict]) -> float:
    """True Average Range: Wilder-style TR (gaps included) over last 14 bars.

    Previously this averaged (high-low) only, which ignores overnight gaps —
    on XAUUSD the Sunday-open and CPI gaps are exactly where stops die.
    """
    trs = []
    window = rows[-15:]
    for i, r in enumerate(window):
        if i == 0:
            continue  # need a previous close for the gap component
        hl = r["high"] - r["low"]
        prev_close = window[i - 1]["close"]
        trs.append(max(hl, abs(r["high"] - prev_close), abs(r["low"] - prev_close)))
    return mean(trs) if trs else 0.0


def classify_bias(rows: list[dict], min_move: float | None = None, min_agreement: int = 3) -> str:
    """Directional bias over the last 5 bars.

    min_move=None → volatility-relative: half the average 5-bar range. The old
    fixed 2.0 USD threshold was applied identically to M5, H1 and H4 — on H4 a
    2 USD move is noise (always 'directional'), on M5 it is a big move (almost
    never). Relative scaling makes the vote meaningful on every timeframe.
    """
    closes = [r["close"] for r in rows[-5:]]
    if len(closes) < 5:
        return "neutral"
    if min_move is None:
        avg_range = mean([r["high"] - r["low"] for r in rows[-5:]]) or 0.5
        min_move = max(0.3, avg_range * 0.5)
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    up_count = sum(1 for d in diffs if d > 0)
    down_count = sum(1 for d in diffs if d < 0)
    net_move = closes[-1] - closes[0]
    if net_move >= min_move and up_count >= min_agreement:
        return "bullish"
    if net_move <= -min_move and down_count >= min_agreement:
        return "bearish"
    return "neutral"



def compute_m5_zones(m5_rows: list[dict], atr: float) -> dict:
    """Compute tighter zones from M5 data for faster entries."""
    lookback = m5_rows[-ZONE_LOOKBACK:]  # 1 hour on M5 — tracks fast-crashing markets
    m5_low = min(r["low"] for r in lookback)
    m5_high = max(r["high"] for r in lookback)
    mid = (m5_low + m5_high) / 2.0
    # Tight zones: 20% ATR from mid for entry areas
    half = atr * 0.25
    return {
        "value_low": round(mid - half, 2),
        "value_high": round(mid + half, 2),
        "long_entry_low": round(mid - half * 1.5, 2),
        "long_entry_high": round(mid - half * 0.3, 2),
        "short_entry_low": round(mid + half * 0.3, 2),
        "short_entry_high": round(mid + half * 1.5, 2),
    }

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
    strong_trend = trend_strength >= 0.35  # ATR units (was 1.5 USD raw)
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
    atr = estimate_atr(m15_rows)
    # Zones come from the last hour of entry-TF structure (M5 in live). The old
    # H1 percentile value zone was computed and immediately overwritten — dead.
    m5_zones = compute_m5_zones(m15_rows, atr)
    value_low = m5_zones["value_low"]
    value_high = m5_zones["value_high"]
    m15_bias = classify_bias(m15_rows)
    h1_bias = classify_bias(h1_rows)
    h4_bias = classify_bias(h4_rows)
    bias = h4_bias if h4_bias != "neutral" else h1_bias
    if bias == "neutral":
        bias = m15_bias
    zones = derive_trade_zones(value_low=value_low, value_high=value_high, atr=atr)
    last_price = m15_rows[-1]["close"]
    # trend_strength = recent push on the ENTRY timeframe, in ATR units of that
    # same timeframe. The old formula divided a 4-bar H4 delta (30-130 USD on
    # gold) by nothing, so every consumer threshold (1.5 / 2.0 / 3 / 12) was
    # permanently saturated: regime always 'trend', grade always 'A',
    # volatility always 'high', momentum always 1.0.
    # Same-TF ratio lands in a sane 0-4 band: 12 bars ≈ 1 hour on M5.
    # Threshold mapping (raw USD → ATR units): 1.5→1.0, 2.0→1.0, 3→1.2,
    # 12→3.0, vol-high 15→3.0, momentum /20 → /2.0.
    push = abs(m15_rows[-1]["close"] - m15_rows[-13]["close"]) if len(m15_rows) >= 13 else 0.0
    trend_strength = round(push / max(atr, 0.01), 2)
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
    execution = _build_execution_plan(bias=bias, zones=zones, atr=atr, regime=regime)
    quality = {
        "trend_strength": trend_strength,
        "alignment": alignment,
        "distance_to_value_low_atr": round(_distance_in_atr(last_price, zones["value_low"], atr), 2),
        "distance_to_value_high_atr": round(_distance_in_atr(last_price, zones["value_high"], atr), 2),
        "bias_votes": {"m15": m15_bias, "h1": h1_bias, "h4": h4_bias},
        "regime": regime,
    }
    # Tight invalidation: recent 1-hour M15 swing ± 0.5 ATR (scalping-grade stop)
    swing_low = min(r["low"] for r in m15_rows[-12:])
    swing_high = max(r["high"] for r in m15_rows[-12:])
    if bias == "bullish":
        invalidation = round(min(swing_low, zones["long_entry_low"]) - (atr * 0.5), 2)
        targets = execution["tp_levels"] or [zones["short_entry_low"], zones["short_entry_high"]]
    elif bias == "bearish":
        invalidation = round(max(swing_high, zones["short_entry_high"]) + (atr * 0.5), 2)
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
