"""SMC / ICT / RTM analysis engine for XAUUSD.

Provides institutional-grade technical analysis:
- Order Block detection (bullish/bearish, mitigated tracking)
- Fair Value Gap detection (bullish/bearish, fill tracking)
- Liquidity sweep / stop hunt detection
- Market structure phase (BOS, CHoCH, range)
- Premium / Discount zones (Fibonacci 0-100%)
- Killzone session timing (London, NY, Asia)
- POI (Point of Interest) quality grading
- Full SMC analysis pipeline
- Merge with classic technical analysis
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# Order Blocks
# ═══════════════════════════════════════════════════════════════════════════════

def detect_order_blocks(rows: list[dict], lookback: int = 20) -> list[dict]:
    """Find unmitigated order blocks.

    Bullish OB = last bearish candle before a strong bullish breakout.
    Bearish OB = last bullish candle before a strong bearish breakout.

    A breakout is "strong" when its body > 1.5× average body.
    """
    if len(rows) < 3:
        return []

    # Compute average body for strength threshold
    bodies = [abs(r["close"] - r["open"]) for r in rows[-lookback:]]
    avg_body = sum(bodies) / len(bodies) if bodies else 0.0
    strong_threshold = max(avg_body * 1.5, sum([r["high"] - r["low"] for r in rows[-lookback:]]) / len(rows[-lookback:]) * 0.5)

    obs = []
    for i in range(len(rows) - 2, 0, -1):
        prev = rows[i - 1]
        curr = rows[i]
        next_c = rows[i + 1]

        # Bullish OB: prev is bearish, curr breaks above with strong body
        if prev["close"] < prev["open"]:
            body_curr = abs(curr["close"] - curr["open"])
            if curr["close"] > curr["open"] and body_curr >= strong_threshold:
                if curr["close"] > prev["high"]:
                    ob = {
                        "type": "bullish",
                        "high": prev["high"],
                        "low": prev["low"],
                        "open": prev["open"],
                        "close": prev["close"],
                        "index": i - 1,
                        "mitigated": False,
                    }
                    obs.append(ob)

        # Bearish OB: prev is bullish, curr breaks below with strong body
        if prev["close"] > prev["open"]:
            body_curr = abs(curr["close"] - curr["open"])
            if curr["close"] < curr["open"] and body_curr >= strong_threshold:
                if curr["close"] < prev["low"]:
                    ob = {
                        "type": "bearish",
                        "high": prev["high"],
                        "low": prev["low"],
                        "open": prev["open"],
                        "close": prev["close"],
                        "index": i - 1,
                        "mitigated": False,
                    }
                    obs.append(ob)

    # Check mitigation: price returning into OB zone
    last_price = rows[-1]["close"]
    for ob in obs:
        if ob["type"] == "bullish" and last_price <= ob["high"]:
            ob["mitigated"] = True
        elif ob["type"] == "bearish" and last_price >= ob["low"]:
            ob["mitigated"] = True

    return obs


# ═══════════════════════════════════════════════════════════════════════════════
# Fair Value Gaps
# ═══════════════════════════════════════════════════════════════════════════════

def detect_fair_value_gaps(rows: list[dict]) -> list[dict]:
    """Find FVGs (3-candle imbalance patterns) across ALL fetched rows.

    Bullish FVG: candle_3.low > candle_1.high  → gap above (buy-side inefficiency)
    Bearish FVG: candle_3.high < candle_1.low  → gap below (sell-side inefficiency)

    b157 (2026-09-08): this function used to carry a `lookback: int = 20`
    parameter that never appeared in the body — the scan is, and always was,
    over the full rows list. The parameter is DELETED (the code stops
    claiming a window it never ran). scripts/b157_smc_window_census.py +
    b157_window_funnel.py MEASURED the honest window before deciding:
    honouring rows[-20:] flips the bias CLASS on 36.8% of 934 historical
    bars, but funnel exp_R gets WORSE, not better — cached +0.003R (noise),
    W1 -0.033R, W2 -0.078R, W3 -0.023R (incumbent bars reproduce the b118
    merit ledger 0.278/0.211/0.230, harness integrity holds). So the stale
    gaps are not a defect to tighten away: the old regime rewards them. Live
    behaviour therefore stays EXACTLY as measured for months; re-testing a
    window is a human-gated bias retune (b89 class), evidence in
    data/backtest/b157_window_funnel*.json.
    Observability instead of behaviour: smc_analyse now stamps an
    `fvg_scan` census (how many unfilled gaps score into bias and how old
    the oldest is, in bars) so the stale contribution is VISIBLE in every
    plan instead of inferable from detector indices.
    """
    if len(rows) < 3:
        return []

    fvgs = []
    for i in range(len(rows) - 2):
        c1 = rows[i]
        c3 = rows[i + 2]

        # Bullish FVG: gap above candle 1
        if c3["low"] > c1["high"]:
            fvgs.append({
                "type": "bullish",
                "low": c1["high"],
                "high": c3["low"],
                "c1_index": i,
                "c3_index": i + 2,
                "filled": False,
            })

        # Bearish FVG: gap below candle 1
        if c3["high"] < c1["low"]:
            fvgs.append({
                "type": "bearish",
                "low": c3["high"],
                "high": c1["low"],
                "c1_index": i,
                "c3_index": i + 2,
                "filled": False,
            })

    # Check fill: subsequent candles' wicks touching the gap
    last_price = rows[-1]["close"]
    for fvg in fvgs:
        # Check candles after the FVG
        for j in range(fvg["c3_index"] + 1, len(rows)):
            candle = rows[j]
            if candle["low"] <= fvg["high"] and candle["high"] >= fvg["low"]:
                fvg["filled"] = True
                break

    return fvgs


def _fvg_scan_census(unfilled_m5: list[dict], unfilled_h1: list[dict],
                     n_rows: int, n_h1: int) -> dict:
    """b157 observability: how far back from the last bar do scoring FVGs sit?

    Age is in bars of each timeframe (bar 0 = the freshest close). M5_ADVERTISED
    / H1_ADVERTISED are the window sizes the deleted `lookback` params claimed;
    `stale_beyond_advertised` counts unfilled gaps older than that which STILL
    score ±1.5 into bias (the design, per the b157 note above — the funnel was
    measured to get WORSE when the window was honoured: cached +0.003R,
    W1 -0.033R, W2 -0.078R, W3 -0.023R).
    """
    M5_ADVERTISED, H1_ADVERTISED = 20, 10
    ages = [n_rows - f.get("c3_index", n_rows) for f in unfilled_m5]
    ages += [n_h1 - f.get("c3_index", n_h1) for f in unfilled_h1]
    stale = (sum(1 for f in unfilled_m5
                 if n_rows - f.get("c3_index", n_rows) > M5_ADVERTISED)
             + sum(1 for f in unfilled_h1
                   if n_h1 - f.get("c3_index", n_h1) > H1_ADVERTISED))
    return {
        "unfilled": len(unfilled_m5) + len(unfilled_h1),
        "stale_beyond_advertised": stale,
        "oldest_age_bars": max(ages) if ages else None,
        "advertised_window_bars": M5_ADVERTISED,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Liquidity Sweep
# ═══════════════════════════════════════════════════════════════════════════════

def detect_liquidity_sweep(rows: list[dict], lookback: int = 5) -> tuple[bool, Optional[float]]:
    """Detect if price swept a significant high/low and reversed.

    Returns (swept: bool, swept_level: float | None).
    Sweep = price breaks previous swing high/low, then reverses direction within 2 candles.
    """
    if len(rows) < 3:
        return False, None

    # Adjust lookback to fit available data
    effective_lookback = min(lookback, len(rows) - 2)
    if effective_lookback < 1:
        return False, None

    window = rows[-(effective_lookback + 2):]

    # Find swing highs/lows in the window (excluding last 2 candles)
    ref_high = max(r["high"] for r in window[:-2])
    ref_low = min(r["low"] for r in window[:-2])

    prev = window[-2]
    curr = window[-1]

    # Sweep of high: current candle breaks above ref_high, then reverses
    if prev["high"] > ref_high and curr["close"] < prev["high"]:
        return True, ref_high

    # Sweep of low: current candle breaks below ref_low, then reverses
    if prev["low"] < ref_low and curr["close"] > prev["low"]:
        return True, ref_low

    # Also check current candle for sweep
    if curr["high"] > ref_high and curr["close"] < ref_high:
        return True, ref_high
    if curr["low"] < ref_low and curr["close"] > ref_low:
        return True, ref_low

    return False, None


# ═══════════════════════════════════════════════════════════════════════════════
# Market Structure
# ═══════════════════════════════════════════════════════════════════════════════

def market_structure_phase(rows: list[dict], lookback: int = 10) -> tuple[str, float]:
    """Determine market structure phase.

    Returns (phase, confidence).
    Phase: bos_bullish, bos_bearish, choch_bullish, choch_bearish, range.
    """
    if len(rows) < 3:
        return "range", 0.0

    window = rows[-min(lookback, len(rows)):]
    if len(window) < 3:
        return "range", 0.0

    # Split into two halves
    mid = max(len(window) // 2, 1)
    first = window[:mid]
    second = window[mid:]

    first_high = max(r["high"] for r in first)
    first_low = min(r["low"] for r in first)
    second_high = max(r["high"] for r in second)
    second_low = min(r["low"] for r in second)

    closes = [r["close"] for r in window]
    last_close = closes[-1]
    first_close = closes[0]

    trend = last_close - first_close
    avg_range = sum(r["high"] - r["low"] for r in window) / max(len(window), 1)

    # Higher high + higher low = bullish BOS
    if second_high > first_high and second_low > first_low:
        return "bos_bullish", min(abs(trend) / avg_range, 1.0) if avg_range > 0 else 0.5

    # Lower low + lower high = bearish BOS
    if second_low < first_low and second_high < first_high:
        return "bos_bearish", min(abs(trend) / avg_range, 1.0) if avg_range > 0 else 0.5

    # Broke both bounds (expanded range) — check net direction
    if second_high > first_high and second_low < first_low:
        if trend > 0:
            return "choch_bullish", 0.6
        else:
            return "choch_bearish", 0.6

    return "range", 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Premium / Discount
# ═══════════════════════════════════════════════════════════════════════════════

def premium_discount_zone(price: float, swing_high: float, swing_low: float) -> dict:
    """Determine where price sits in the swing range.

    Returns {zone: premium|equilibrium|discount, fib_level: 0.0-1.0, quality: 0-100}.
    """
    if swing_high <= swing_low:
        return {"zone": "equilibrium", "fib_level": 0.5, "quality": 0}

    range_size = swing_high - swing_low
    position = (price - swing_low) / range_size  # 0.0 (at low) to 1.0 (at high)
    fib_level = position

    if fib_level <= 0.25:
        zone = "discount"
        # Quality: how deep in discount — deeper = better for buys
        quality = round((0.25 - fib_level) / 0.25 * 100, 0)
    elif fib_level >= 0.75:
        zone = "premium"
        # Quality: how deep in premium — deeper = better for sells
        quality = round((fib_level - 0.75) / 0.25 * 100, 0)
    else:
        zone = "equilibrium"
        quality = 50 - abs(fib_level - 0.5) * 200  # closer to 0.5 = worse

    return {
        "zone": zone,
        "fib_level": round(fib_level, 3),
        "quality": max(0, min(100, quality)),
        "swing_high": swing_high,
        "swing_low": swing_low,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Killzone Timing
# ═══════════════════════════════════════════════════════════════════════════════

KILLZONES = {
    "london":   {"start": (7, 0), "end": (9, 30), "weight": 1.0},    # UTC
    "newyork":  {"start": (12, 0), "end": (15, 0), "weight": 1.0},
    "london_close": {"start": (15, 0), "end": (16, 0), "weight": 0.5},
    "asia":     {"start": (0, 0), "end": (5, 0), "weight": 0.6},
}


def active_killzone_session(now: datetime) -> tuple[str, float]:
    """Determine which killzone is active based on UTC time.

    Returns (session_name: str, weight: float 0.0-1.0).
    Weight 0 means dead zone (no trading).
    """
    hour = now.hour + now.minute / 60.0

    for name, zone in KILLZONES.items():
        start_h = zone["start"][0] + zone["start"][1] / 60.0
        end_h = zone["end"][0] + zone["end"][1] / 60.0

        # b157: a duplicate-condition branch for the 15:00-16:00 zone sat
        # under this loop, unreachable by construction; deleted, behaviour
        # identical (KILLZONES already maps that hour).
        if start_h <= hour < end_h:
            return name, zone["weight"]

    return "dead", 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# POI Grading
# ═══════════════════════════════════════════════════════════════════════════════

def grade_poi(
    has_ob: bool, ob_mitigated: bool,
    has_fvg: bool, fvg_filled: bool,
    liq_sweep: bool,
    discount: bool,  # True = in discount for buys, in premium for sells
    killzone_weight: float,
    structure_aligned: bool,
) -> str:
    """Grade a Point of Interest (POI) based on SMC signal confluence.

    A+: Perfect confluence (OB + FVG + sweep + zone + time + structure)
    A:  Strong confluence (5/6)
    B:  Moderate (3-4/6)
    C:  Weak (0-2/6)

    b157 FINDING (documented, NOT changed): smc_analyse feeds this only the
    entry-TF sets (has_ob/has_fvg come from the M5/M15 rows), while
    _derive_smc_bias merges M5+H1 — POI grade and bias see different worlds.
    Grep-verified: nothing on the decision path consumes `poi` (only
    ctx['quality']['smc_poi'], a plan-record label), so wiring H1 into the
    grade would move a DISPLAYED label with no gate behind it; left for a
    measured round rather than a cosmetic edit. Filed as follow-up todo.
    """
    score = 0.0

    if has_ob and not ob_mitigated:
        score += 2.0
    if has_fvg and not fvg_filled:
        score += 1.5
    if liq_sweep:
        score += 1.5
    if discount:
        score += 1.0
    if killzone_weight >= 0.8:
        score += 1.5
    elif killzone_weight >= 0.5:
        score += 0.5
    if structure_aligned:
        score += 1.0

    max_score = 8.5
    ratio = score / max_score

    if ratio >= 0.85:
        return "A+"
    elif ratio >= 0.70:
        return "A"
    elif ratio >= 0.45:
        return "B"
    else:
        return "C"


# ═══════════════════════════════════════════════════════════════════════════════
# Full SMC Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def smc_analyse(rows: list[dict], now: Optional[datetime] = None, h1_rows: Optional[list[dict]] = None) -> dict:
    """Run full SMC/ICT/RTM analysis on price data.

    Args:
        rows: OHLC candles (M15 preferred). Must have open/high/low/close/time.
        now: Current datetime for killzone detection.
        h1_rows: Optional H1 candles for higher-timeframe structure analysis.

    Returns complete SMC analysis dict with bias, signal, confidence, etc.
    """
    if now is None:
        now = datetime.utcnow()

    if len(rows) < 10:
        return _empty_smc_result(now)

    _h1 = h1_rows if h1_rows and len(h1_rows) >= 10 else None

    # ── 1. Order blocks (M15) ──
    obs = detect_order_blocks(rows)
    unmitigated_obs = [o for o in obs if not o["mitigated"]]
    has_active_ob = len(unmitigated_obs) > 0
    nearest_ob = unmitigated_obs[-1] if unmitigated_obs else None

    # H1 order blocks for higher-timeframe context
    h1_obs = detect_order_blocks(_h1, lookback=15) if _h1 else []
    h1_unmitigated = [o for o in h1_obs if not o["mitigated"]]

    # ── 2. Fair value gaps (M15) ──
    fvgs = detect_fair_value_gaps(rows)
    unfilled_fvgs = [f for f in fvgs if not f["filled"]]
    has_active_fvg = len(unfilled_fvgs) > 0
    nearest_fvg = unfilled_fvgs[-1] if unfilled_fvgs else None

    # H1 FVGs
    h1_fvgs = detect_fair_value_gaps(_h1) if _h1 else []
    h1_unfilled = [f for f in h1_fvgs if not f["filled"]]

    # ── 3. Liquidity sweep (M15) ──
    swept, swept_level = detect_liquidity_sweep(rows)

    # ── 4. Market structure (M15 + H1) ──
    structure_phase, structure_confidence = market_structure_phase(rows)
    h1_structure_phase, h1_structure_confidence = market_structure_phase(_h1) if _h1 else ("unknown", 0.0)

    # ── 5. Premium/Discount — wider swing from H1 if available ──
    if _h1:
        recent_h1 = _h1[-15:] if len(_h1) >= 15 else _h1
        swing_high = max(r["high"] for r in recent_h1)
        swing_low = min(r["low"] for r in recent_h1)
    else:
        recent = rows[-20:] if len(rows) >= 20 else rows
        swing_high = max(r["high"] for r in recent)
        swing_low = min(r["low"] for r in recent)
    last_price = rows[-1]["close"]
    pd_zone = premium_discount_zone(last_price, swing_high, swing_low)

    # ── 6. Killzone ──
    killzone_session, killzone_weight = active_killzone_session(now)

    # ── 6b. b157 OBSERVABILITY: how much of the bias weight is stale? ──
    # The scan is unbounded by design (see detect_fair_value_gaps' b157
    # note); this census makes the stale contribution VISIBLE per plan.
    # ADVERTISED_WINDOW_BARS is what the old signature claimed (M5 20 bars /
    # H1 10); gaps older than it still score, and `stale_*` counts how many.
    fvg_scan = _fvg_scan_census(unfilled_fvgs, h1_unfilled,
                                n_rows=len(rows), n_h1=len(_h1 or []))

    # ── 7. Bias from SMC signals (now includes H1 OBs/FVGs) ──
    smc_bias, smc_confidence = _derive_smc_bias(
        obs + h1_obs, unmitigated_obs + h1_unmitigated,
        fvgs + h1_fvgs, unfilled_fvgs + h1_unfilled,
        swept, structure_phase, pd_zone, killzone_weight,
    )

    # ── 8. Signal ──
    signal, signal_confidence = _compute_smc_signal(
        smc_bias, smc_confidence, pd_zone, killzone_weight, structure_phase,
    )

    # ── 9. POI grade ──
    structure_aligned = (
        (smc_bias == "bullish" and structure_phase in ("bos_bullish", "choch_bullish"))
        or (smc_bias == "bearish" and structure_phase in ("bos_bearish", "choch_bearish"))
    )
    in_good_zone = (
        (smc_bias == "bullish" and pd_zone["zone"] == "discount")
        or (smc_bias == "bearish" and pd_zone["zone"] == "premium")
    )
    poi_grade = grade_poi(
        has_ob=has_active_ob, ob_mitigated=False,
        has_fvg=has_active_fvg, fvg_filled=False,
        liq_sweep=swept,
        discount=in_good_zone,
        killzone_weight=killzone_weight,
        structure_aligned=structure_aligned,
    )

    # ── 10. Advanced ICT concepts ──
    breaker_blocks = detect_breaker_blocks(rows)
    rejection_blocks = detect_rejection_blocks(rows)
    ote_raw = compute_ote_zone(swing_low, swing_high, direction=smc_bias)
    ote_zone = {k: v for k, v in ote_raw.items() if k != "in_zone"}
    power_of_three = detect_power_of_three(rows)
    turtle_soup = detect_turtle_soup(rows)
    silver_bullet = evaluate_silver_bullet_setup(now)
    session_liquidity = compute_session_liquidity(rows)
    volume_imbalance = detect_volume_imbalance(rows)

    return {
        "order_blocks": obs,
        "active_order_blocks": unmitigated_obs,
        "nearest_ob": nearest_ob,
        "fvgs": fvgs,
        "active_fvgs": unfilled_fvgs,
        "nearest_fvg": nearest_fvg,
        "liquidity_sweep": {"swept": swept, "level": swept_level},
        "fvg_scan": fvg_scan,
        "market_structure": {"phase": structure_phase, "confidence": structure_confidence},
        "premium_discount": pd_zone,
        "killzone": {"session": killzone_session, "weight": killzone_weight},
        "bias": smc_bias,
        "confidence": smc_confidence,
        "signal": signal,
        "signal_confidence": signal_confidence,
        "poi": poi_grade,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "last_price": last_price,
        "smc_weight": killzone_weight if killzone_weight > 0.3 else 0.5,
        # ── Higher timeframe ──
        "h1_structure": {"phase": h1_structure_phase, "confidence": h1_structure_confidence},
        "h1_order_blocks": h1_obs,
        "h1_active_order_blocks": h1_unmitigated,
        "h1_fvgs": h1_fvgs,
        "h1_active_fvgs": h1_unfilled,
        # ── Advanced ICT ──
        "breaker_blocks": breaker_blocks,
        "rejection_blocks": rejection_blocks,
        "ote_zone": ote_zone,
        "power_of_three": power_of_three,
        "turtle_soup": turtle_soup,
        "silver_bullet": silver_bullet,
        "session_liquidity": session_liquidity,
        "volume_imbalance": volume_imbalance,
    }


def _empty_smc_result(now: datetime) -> dict:
    """Return minimal result when insufficient data."""
    return {
        "order_blocks": [], "active_order_blocks": [], "nearest_ob": None,
        "fvgs": [], "active_fvgs": [], "nearest_fvg": None,
        "liquidity_sweep": {"swept": False, "level": None},
        "fvg_scan": {"unfilled": 0, "stale_beyond_advertised": 0,
                     "oldest_age_bars": None, "advertised_window_bars": 20},
        "market_structure": {"phase": "range", "confidence": 0.0},
        "premium_discount": {"zone": "equilibrium", "fib_level": 0.5, "quality": 0},
        "killzone": {"session": "dead", "weight": 0.0},
        "bias": "neutral", "confidence": 0.0,
        "signal": "wait", "signal_confidence": 0.0,
        "poi": "C", "swing_high": 0, "swing_low": 0, "last_price": 0,
        "smc_weight": 0.3,
        "h1_structure": {"phase": "unknown", "confidence": 0.0},
        "h1_order_blocks": [], "h1_active_order_blocks": [],
        "h1_fvgs": [], "h1_active_fvgs": [],
        "breaker_blocks": [], "rejection_blocks": [],
        "ote_zone": None, "power_of_three": None,
        "turtle_soup": None, "silver_bullet": None,
        "session_liquidity": None, "volume_imbalance": [],
    }


def _derive_smc_bias(
    obs, unmitigated_obs, fvgs, unfilled_fvgs,
    swept, structure_phase, pd_zone, killzone_weight,
) -> tuple[str, float]:
    """Derive SMC-based market bias from all signals."""
    bullish_score = 0.0
    bearish_score = 0.0

    # OB signals
    if unmitigated_obs:
        for ob in unmitigated_obs:
            if ob["type"] == "bullish":
                bullish_score += 2.0
            else:
                bearish_score += 2.0

    # FVG signals
    if unfilled_fvgs:
        for fvg in unfilled_fvgs:
            if fvg["type"] == "bullish":
                bullish_score += 1.5
            else:
                bearish_score += 1.5

    # Structure
    if structure_phase == "bos_bullish":
        bullish_score += 2.5
    elif structure_phase == "bos_bearish":
        bearish_score += 2.5
    elif structure_phase == "choch_bullish":
        bullish_score += 1.5
    elif structure_phase == "choch_bearish":
        bearish_score += 1.5

    # Premium/Discount
    if pd_zone["zone"] == "discount":
        bullish_score += pd_zone["quality"] / 50.0
    elif pd_zone["zone"] == "premium":
        bearish_score += pd_zone["quality"] / 50.0

    # Killzone weight
    bullish_score *= max(killzone_weight, 0.5)
    bearish_score *= max(killzone_weight, 0.5)

    diff = bullish_score - bearish_score
    total = bullish_score + bearish_score
    confidence = min(abs(diff) / (total + 0.01), 1.0)

    if diff > 1.0:
        return "bullish", confidence
    elif diff < -1.0:
        return "bearish", confidence
    else:
        return "neutral", 0.0


def _compute_smc_signal(bias, bias_confidence, pd_zone, killzone_weight, structure_phase) -> tuple[str, float]:
    """Compute final trade signal."""
    if bias == "neutral" or bias_confidence < 0.4:
        return "wait", 0.0

    if killzone_weight < 0.1:
        # Dead zone (weekend/after close) — keep signal but dampen
        return bias, bias_confidence * 0.3

    if bias == "bullish" and pd_zone["zone"] == "premium":
        # Don't buy at premium
        return "wait", 0.3
    if bias == "bearish" and pd_zone["zone"] == "discount":
        return "wait", 0.3

    return bias, bias_confidence


# ═══════════════════════════════════════════════════════════════════════════════
# Merge SMC with Classic
# ═══════════════════════════════════════════════════════════════════════════════

def merge_smc_with_classic(classic_context: dict, smc_result: dict) -> dict:
    """Merge SMC analysis with classic technical analysis.

    Returns enriched context with weighted consensus bias, confidence,
    and both source analyses preserved.
    """
    classic_bias = classic_context.get("bias", "neutral")
    classic_regime = classic_context.get("regime", "range")
    classic_quality = classic_context.get("quality", {})
    classic_alignment = classic_quality.get("alignment", "neutral")

    smc_bias = smc_result.get("bias", "neutral")
    smc_confidence = smc_result.get("confidence", 0.0)
    smc_signal = smc_result.get("signal", "wait")
    smc_weight = smc_result.get("smc_weight", 0.5)

    # Compute classic confidence from alignment and regime
    classic_confidence = 0.0
    if classic_alignment == "aligned":
        classic_confidence = 0.7
    elif classic_alignment == "mixed":
        classic_confidence = 0.4
    if classic_regime == "range":
        classic_confidence *= 0.5

    # Weighted consensus — give SMC more weight when classic is neutral
    bias_scores = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}

    if classic_bias == "bullish":
        bias_scores["bullish"] += classic_confidence * 0.4
    elif classic_bias == "bearish":
        bias_scores["bearish"] += classic_confidence * 0.4
    else:
        # Classic neutral = no opinion, just a tiny neutral anchor
        bias_scores["neutral"] += 0.05

    # SMC contribution: when classic is neutral, SMC dominates
    if classic_bias == "neutral":
        smc_factor = smc_confidence * 0.9  # high trust when classic has no opinion
    elif smc_bias == classic_bias:
        smc_factor = smc_confidence * smc_weight * 0.7  # agreement boost
    else:
        smc_factor = smc_confidence * smc_weight * 0.4  # divergent, cautious

    if smc_bias == "bullish":
        bias_scores["bullish"] += smc_factor
    elif smc_bias == "bearish":
        bias_scores["bearish"] += smc_factor

    # Determine winner
    max_bias = max(bias_scores, key=bias_scores.get)
    max_score = bias_scores[max_bias]

    merged_confidence = round(max_score, 2)
    if merged_confidence < 0.20:
        max_bias = "neutral"
        merged_confidence = 0.0

    # Compute action
    if max_bias == "neutral":
        action = "wait"
    elif smc_signal == "wait" and smc_confidence > 0.5:
        action = "wait" if merged_confidence < 0.5 else max_bias
    elif max_bias == "bullish":
        action = "long" if merged_confidence >= 0.30 else "wait"
    elif max_bias == "bearish":
        action = "short" if merged_confidence >= 0.30 else "wait"
    else:
        action = "wait"

    return {
        "bias": max_bias,
        "confidence": merged_confidence,
        "action": action,
        "classic_source": {
            "bias": classic_bias,
            "confidence": classic_confidence,
            "regime": classic_regime,
            "alignment": classic_alignment,
        },
        "smc_source": {
            "bias": smc_bias,
            "signal": smc_signal,
            "confidence": smc_confidence,
            "weight": smc_weight,
            "poi": smc_result.get("poi"),
            "market_structure": smc_result.get("market_structure"),
            "killzone": smc_result.get("killzone"),
        },
        "smc_result": smc_result,  # Full SMC result for reference
    }


# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# ADVANCED SMC/ICT/RTM CONCEPTS
# ═══════════════════════════════════════════════════════════════════════════════

# ── 1. Breaker Block ─────────────────────────────────────────────────────────

def detect_breaker_blocks(rows: list[dict], lookback: int = 10) -> list[dict]:
    """Detect OBs that were broken and now act as flipped S/R.

    Bullish OB broken -> becomes bearish breaker (resistance).
    Bearish OB broken -> becomes bullish breaker (support).
    """
    obs = detect_order_blocks(rows, lookback)
    if not obs:
        return []
    breakers = []
    last_close = rows[-1]["close"]
    for ob in obs:
        ob_high = ob["high"]
        ob_low = ob["low"]
        broke = False
        broke_dir = None
        for r in rows[ob["index"] + 1:]:
            if ob["type"] == "bullish" and r["close"] < ob_low:
                broke = True
                broke_dir = "below"
                break
            elif ob["type"] == "bearish" and r["close"] > ob_high:
                broke = True
                broke_dir = "above"
                break
        if not broke:
            continue
        if ob["type"] == "bullish" and broke_dir == "below":
            if ob_low <= last_close <= ob_high:
                breakers.append({"type": "bearish_breaker", "high": ob_high, "low": ob_low, "original_ob": ob, "flipped": True})
        elif ob["type"] == "bearish" and broke_dir == "above":
            if ob_low <= last_close <= ob_high:
                breakers.append({"type": "bullish_breaker", "high": ob_high, "low": ob_low, "original_ob": ob, "flipped": True})
    return breakers


# ── 2. Rejection Block ───────────────────────────────────────────────────────

def detect_rejection_blocks(rows: list[dict], lookback: int = 10) -> list[dict]:
    """Detect pin bar / wick rejections at active OBs."""
    obs = detect_order_blocks(rows, lookback)
    active_obs = [o for o in obs if not o["mitigated"]]
    if not active_obs:
        return []
    rejections = []
    last = rows[-1]
    body = abs(last["close"] - last["open"])
    upper_wick = last["high"] - max(last["close"], last["open"])
    lower_wick = min(last["close"], last["open"]) - last["low"]
    for ob in active_obs:
        if ob["type"] == "bullish":
            # Wick dips into OB zone
            if last["low"] <= ob["high"] and lower_wick >= body * 0.5:
                rejections.append({"type": "bullish_rejection", "ob": ob, "wick_size": lower_wick})
        else:
            # Upper wick reaches into OB zone
            if last["high"] >= ob["low"] and upper_wick >= body * 0.5:
                rejections.append({"type": "bearish_rejection", "ob": ob, "wick_size": upper_wick})
    return rejections


# ── 3. OTE (Optimal Trade Entry) ─────────────────────────────────────────────

def compute_ote_zone(swing_low: float, swing_high: float, direction: str = "bullish") -> dict:
    """Fibonacci 0.62-0.79 retracement zone."""
    if swing_high <= swing_low:
        return {"low": swing_low, "high": swing_low, "in_zone": lambda p: False, "fib_range": [0.62, 0.79]}
    fib_62 = swing_high - 0.62 * (swing_high - swing_low)
    fib_79 = swing_high - 0.79 * (swing_high - swing_low)
    ote_low = min(fib_62, fib_79)
    ote_high = max(fib_62, fib_79)
    def in_zone(price):
        return ote_low <= price <= ote_high
    return {"low": ote_low, "high": ote_high, "in_zone": in_zone, "fib_range": [0.62, 0.79]}


# ── 4. Power of 3 ────────────────────────────────────────────────────────────

def detect_power_of_three(rows: list[dict]) -> dict:
    """Accumulation -> Manipulation -> Distribution."""
    n = len(rows)
    if n < 6:
        return {"phase": "not_enough_data", "accumulation": {}, "manipulation": {}, "distribution": {}}
    third = n // 3
    acc = rows[:third]
    manip = rows[third:2 * third]
    dist = rows[2 * third:]
    ar = {"high": max(r["high"] for r in acc), "low": min(r["low"] for r in acc)}
    mr = {"high": max(r["high"] for r in manip), "low": min(r["low"] for r in manip)}
    dr = {"high": max(r["high"] for r in dist), "low": min(r["low"] for r in dist)}
    if (mr["high"] > ar["high"] and dr["high"] > ar["high"]) or (mr["low"] < ar["low"] and dr["low"] < ar["low"]):
        phase = "distribution"
    elif mr["high"] > ar["high"] or mr["low"] < ar["low"]:
        phase = "manipulation"
    else:
        phase = "accumulation"
    return {"phase": phase, "accumulation": ar, "manipulation": mr, "distribution": dr}


# ── 5. Turtle Soup ───────────────────────────────────────────────────────────

def detect_turtle_soup(rows: list[dict], lookback: int = 10) -> dict:
    """Detect fake breakout then sharp reversal."""
    if len(rows) < 4:
        return {"found": False, "type": None, "fake_level": None}
    window = rows[-min(lookback, len(rows)):]
    sw_high = max(r["high"] for r in window[:-2])
    sw_low = min(r["low"] for r in window[:-2])
    fake = window[-2]
    confirm = window[-1]
    if fake["low"] < sw_low and confirm["close"] > confirm["open"] and confirm["close"] > fake["high"] * 0.98:
        return {"found": True, "type": "bullish", "fake_level": sw_low}
    if fake["high"] > sw_high and confirm["close"] < confirm["open"] and confirm["close"] < fake["low"] * 1.02:
        return {"found": True, "type": "bearish", "fake_level": sw_high}
    return {"found": False, "type": None, "fake_level": None}


# ── 6. Silver Bullet ─────────────────────────────────────────────────────────

def evaluate_silver_bullet_setup(now=None) -> dict:
    """10-11 AM and 2-3 PM NY time windows."""
    if now is None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
    hour = now.hour
    minute = now.minute
    am = (hour == 14 and 0 <= minute < 60)
    pm = (hour == 18 or (hour == 19 and 0 <= minute < 60))
    if am:
        return {"active": True, "window": "am", "label": "Silver Bullet AM (10-11 NY)"}
    elif pm:
        return {"active": True, "window": "pm", "label": "Silver Bullet PM (2-3 NY)"}
    return {"active": False, "window": None, "label": None}


# ── 7. Session Liquidity ─────────────────────────────────────────────────────

def compute_session_liquidity(rows: list[dict], session: str = "asia") -> dict:
    """Compute session highs, lows, midpoint, and sweep detection.

    BUG FIX 2026-08-30: swept_* compared the last 3 bars against a range
    that INCLUDED them — max(high) can never be exceeded by its own member,
    so both flags were mathematically always False (dead detector).
    The range must come from the earlier bars; the last 3 are the sweepers.
    """
    if not rows:
        return {"session_high": 0.0, "session_low": 0.0, "midpoint": 0.0, "swept_high": False, "swept_low": False, "session": session, "range": 0.0}
    base = rows[:-3] if len(rows) > 3 else rows
    tail = rows[-3:] if len(rows) > 3 else []
    sh = max(r["high"] for r in base)
    sl = min(r["low"] for r in base)
    return {
        "session": session, "session_high": sh, "session_low": sl,
        "midpoint": round((sh + sl) / 2, 2),
        "swept_high": any(r["high"] > sh for r in tail),
        "swept_low": any(r["low"] < sl for r in tail),
        "range": round(sh - sl, 2),
    }


# ── 8. Volume Imbalance ──────────────────────────────────────────────────────

def detect_volume_imbalance(rows: list[dict], threshold: float = 2.5) -> list[dict]:
    """Detect volume spikes > threshold * avg_volume."""
    if len(rows) < 3:
        return []
    vols = [r.get("tick_volume", 0) for r in rows]
    avg_vol = sum(vols) / max(len(vols), 1)
    if avg_vol <= 0:
        return []
    imbalances = []
    for i, r in enumerate(rows):
        vol = r.get("tick_volume", 0)
        if vol > avg_vol * threshold:
            direction = "bullish" if r["close"] > r["open"] else "bearish"
            imbalances.append({"index": i, "volume": vol, "avg_volume": round(avg_vol, 1), "volume_multiple": round(vol / avg_vol, 2), "direction": direction})
    return imbalances
