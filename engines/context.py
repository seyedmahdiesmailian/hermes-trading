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


# H1 structure zones (B1): last N hours of H1 define discount/premium.
# The old 12-bar M5 mid produced a ~0.5 ATR value zone (~$2 on gold) and a
# plan-TP1/SL RR median of 0.24 — 91% of live plans failed MIN_RR=1.5 and
# were then reanchored into a 1.5R scalp whose winners the manager cut.
H1_ZONE_BARS = 24
DISCOUNT_FRACTION = 0.30
PREMIUM_FRACTION = 0.30
INVALIDATION_ATR_BUFFER = 0.35


def compute_htf_structure_zones(h1_rows: list[dict], atr: float) -> dict:
    """Entry zones from the H1 swing, not the last hour of M5 noise."""
    if not h1_rows:
        return {}
    lookback = h1_rows[-H1_ZONE_BARS:] if len(h1_rows) >= 8 else h1_rows
    swing_low = min(r["low"] for r in lookback)
    swing_high = max(r["high"] for r in lookback)
    rng = swing_high - swing_low
    atr = float(atr or 0) or 5.0
    if rng < max(atr * 0.8, 1.0):
        mid = (swing_low + swing_high) / 2.0
        half = max(atr * 1.0, 2.0)
        swing_low = mid - half
        swing_high = mid + half
        rng = swing_high - swing_low
    discount_hi = swing_low + DISCOUNT_FRACTION * rng
    premium_lo = swing_high - PREMIUM_FRACTION * rng
    return {
        "value_low": round(discount_hi, 2),
        "value_high": round(premium_lo, 2),
        "long_entry_low": round(swing_low, 2),
        "long_entry_high": round(discount_hi, 2),
        "short_entry_low": round(premium_lo, 2),
        "short_entry_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "swing_high": round(swing_high, 2),
        "zone_source": "h1_swing",
    }


def apply_bias_geometry(ctx: dict) -> bool:
    """Recompute execution / invalidation / targets for ctx['bias'].

    Called at plan birth AND after SMC flips the direction (A2). Empty or
    incomplete zones return False and leave the existing levels alone so
    lab fixtures that only carry invalidation keep working.
    """
    zones = ctx.get("zones") or {}
    needed = ("value_low", "value_high", "long_entry_low", "long_entry_high",
              "short_entry_low", "short_entry_high")
    try:
        if any(zones.get(k) is None for k in needed):
            return False
        atr = float(ctx.get("atr") or 0) or 5.0
    except (TypeError, ValueError):
        return False
    bias = ctx.get("bias") or "neutral"
    regime = (ctx.get("quality") or {}).get("regime") or "range"
    if bias not in {"bullish", "bearish"}:
        regime = "range"
    execution = _build_execution_plan(bias=bias, zones=zones, atr=atr, regime=regime)
    swing_low = float(zones.get("swing_low") or zones["long_entry_low"])
    swing_high = float(zones.get("swing_high") or zones["short_entry_high"])
    if bias == "bullish":
        invalidation = round(swing_low - (atr * INVALIDATION_ATR_BUFFER), 2)
        targets = execution["tp_levels"] or [zones["short_entry_low"], zones["short_entry_high"]]
    elif bias == "bearish":
        invalidation = round(swing_high + (atr * INVALIDATION_ATR_BUFFER), 2)
        targets = execution["tp_levels"] or [zones["long_entry_high"], zones["long_entry_low"]]
    else:
        invalidation = round(swing_low - (atr * 0.25), 2)
        targets = []
    ctx["execution"] = execution
    ctx["invalidation"] = invalidation
    ctx["targets"] = targets
    return True


def _alignment_label(m5_bias: str, h1_bias: str, h4_bias: str) -> str:
    votes = [m5_bias, h1_bias, h4_bias]
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
    m5_bias: str,
    h1_bias: str,
    h4_bias: str,
) -> str:
    strong_trend = trend_strength >= 0.35  # ATR units (was 1.5 USD raw)
    higher_tf_aligned = h1_bias == h4_bias and h1_bias in {"bullish", "bearish"}
    pullback_alignment = higher_tf_aligned and m5_bias not in {h1_bias, "neutral"}

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
    # Neutral is not a short: the old else-branch built SELL geometry for
    # any non-bullish bias, including wait states after a merge veto.
    if bias not in {"bullish", "bearish"}:
        regime = "range"
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


def build_plan_context(m5_rows: list[dict], h1_rows: list[dict], h4_rows: list[dict], session_name: str,
                       m15_rows: list[dict] | None = None) -> dict:
    """Multi-TF plan context. m15_rows (b28) is an ANALYTICAL VOTE only:
    recorded in bias_votes for reports/learning, never decides the entry.
    A/B on 282h real data (scripts/ab_entry_tf.py) showed M15 as an entry
    lane is worse than M5 (+991 vs +1680 $/1000h, unique trades WR 48%)."""
    atr = estimate_atr(m5_rows)
    m5_bias = classify_bias(m5_rows)
    m15_bias = classify_bias(m15_rows) if m15_rows else None
    h1_bias = classify_bias(h1_rows)
    h4_bias = classify_bias(h4_rows)
    # B3: a directional plan needs H4 to take a side. Falling back to H1/M5
    # while H4 is neutral is how the book sold into the larger uptrend
    # (journal: 22 SELL −$128 vs 12 BUY +$26). Votes are still recorded.
    bias = h4_bias if h4_bias in {"bullish", "bearish"} else "neutral"
    zones = compute_htf_structure_zones(h1_rows, atr)
    if not zones:
        m5_zones = compute_m5_zones(m5_rows, atr)
        zones = derive_trade_zones(
            value_low=m5_zones["value_low"],
            value_high=m5_zones["value_high"],
            atr=atr,
        )
        swing_window = m5_rows[-12:] if len(m5_rows) >= 12 else m5_rows
        zones["swing_low"] = round(min(r["low"] for r in swing_window), 2)
        zones["swing_high"] = round(max(r["high"] for r in swing_window), 2)
        zones["zone_source"] = "m5_fallback"
    last_price = m5_rows[-1]["close"]
    # trend_strength = recent push on the ENTRY timeframe, in ATR units of that
    # same timeframe. The old formula divided a 4-bar H4 delta (30-130 USD on
    # gold) by nothing, so every consumer threshold (1.5 / 2.0 / 3 / 12) was
    # permanently saturated: regime always 'trend', grade always 'A',
    # volatility always 'high', momentum always 1.0.
    # Same-TF ratio lands in a sane 0-4 band: 12 bars ≈ 1 hour on M5.
    # Threshold mapping (raw USD → ATR units): 1.5→1.0, 2.0→1.0, 3→1.2,
    # 12→3.0, vol-high 15→3.0, momentum /20 → /2.0.
    push = abs(m5_rows[-1]["close"] - m5_rows[-13]["close"]) if len(m5_rows) >= 13 else 0.0
    trend_strength = round(push / max(atr, 0.01), 2)
    alignment = _alignment_label(m5_bias, h1_bias, h4_bias)
    regime = _detect_regime(
        bias=bias,
        alignment=alignment,
        trend_strength=trend_strength,
        last_price=last_price,
        value_low=zones["value_low"],
        value_high=zones["value_high"],
        atr=atr,
        m5_bias=m5_bias,
        h1_bias=h1_bias,
        h4_bias=h4_bias,
    )
    quality = {
        "trend_strength": trend_strength,
        "alignment": alignment,
        "distance_to_value_low_atr": round(_distance_in_atr(last_price, zones["value_low"], atr), 2),
        "distance_to_value_high_atr": round(_distance_in_atr(last_price, zones["value_high"], atr), 2),
        "bias_votes": {"m5": m5_bias, "h1": h1_bias, "h4": h4_bias,
                       **({"m15": m15_bias} if m15_bias else {})},
        "regime": regime,
        "zone_source": zones.get("zone_source", "h1_swing"),
        "htf_bias": h4_bias,
    }
    ctx = {
        "symbol": "XAUUSD",
        "session": session_name,
        "bias": bias,
        "atr": atr,
        "zones": zones,
        "quality": quality,
        "context": {
            "m5_last": last_price,
            "h1_last": h1_rows[-1]["close"],
            "h4_last": h4_rows[-1]["close"],
        },
    }
    apply_bias_geometry(ctx)
    return ctx
