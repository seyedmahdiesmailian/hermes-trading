from __future__ import annotations

from datetime import datetime, timezone

# b54: strategy knobs as patchable module constants (swept by
# scripts/ab_b54_sweep.py on the live-parity M5 funnel; values = live as-is).
# SMC_CONF_FLOOR gates every no-trigger aggressive lane (4 call sites).
SMC_CONF_FLOOR = 0.4
# Late entries re-anchor their stop to min(structure, price ± cap*ATR).
REANCHOR_STOP_ATR_CAP = 2.0
# ...and keep at least this reward:risk after re-anchoring.
REANCHOR_MIN_RR = 1.5


def setup_grade(plan: dict) -> str:
    """THE canonical setup grade from plan quality — one definition, three
    consumers (the entry gate, the runtime ladder, the watchdog ladder).

    b45 FIX 2026-08-31: 'mixed' alignment no longer qualifies for B.
    Evidence: the two mixed/range sells at 14:15/14:30 UTC (counter-trend
    entries into a rising market with contradictory TF votes) netted -56.7$
    (+37.67 / -94.38), while every aligned plan that day was profitable.
    Mixed votes = coin flip = C = blocked by MIN_SETUP_GRADE.

    b111 (2026-09-07): this rule used to live twice — here-ish in
    engines/auto_executor.py and again in hermes_runtime.py — while
    position_daemon.build_trade inlined a looser PRE-b45 rule (no regime
    clause for an A, 'mixed' reaching B). That third copy is now this
    function. The divergence was measured inert before it was removed
    (scripts/b111_blast_radius_probe.py, ledger
    data/backtest/b111_blast_radius.json): the only cell where the two rules
    produce a different broker-visible action is aligned + trend>=3.0 + a
    NON-continuation regime, and engines.context._detect_regime cannot emit
    that combination (0 of 320 swept vote x trend x geometry cells), so the
    watchdog's looser A was unreachable and its looser B sat in a lane that
    post-b55 closes the full position at TP1 either way.

    This module is a LEAF (stdlib imports only) on purpose: the grade is read
    by the entry gate, the runtime and the watchdog, and a shared definition
    must not create an import cycle between any of them.
    """
    q = plan.get("quality", {}) or {}
    alignment = q.get("alignment")
    trend = float(q.get("trend_strength", 0) or 0)
    regime = q.get("regime")
    if (alignment == "aligned" and trend >= 3.0
            and regime in {"breakout_continuation", "pullback_continuation"}):
        return "A"
    if alignment == "aligned" and trend >= 1.2:
        return "B"
    return "C"


def classify_price_location(price: float, zones: dict) -> str:
    if zones["long_entry_low"] <= price <= zones["long_entry_high"]:
        return "long_zone"
    if zones["short_entry_low"] <= price <= zones["short_entry_high"]:
        return "short_zone"
    if zones["value_low"] <= price <= zones["value_high"]:
        return "value_zone"
    if price < zones["value_low"]:
        return "discount"
    return "premium"


def build_trade_blueprint(plan: dict, price: float, trigger_ok: bool) -> dict:
    zone = classify_price_location(price, plan["zones"])
    side = "BUY" if plan["bias"] == "bullish" else "SELL"
    execution = plan.get("execution", {})
    tp_levels = execution.get("tp_levels") or plan.get("targets", [])
    tp = tp_levels[0] if tp_levels else plan["targets"][0]
    return {
        "symbol": plan["symbol"],
        "side": side,
        "entry_zone": zone,
        "entry_price": price,
        "trigger_ok": trigger_ok,
        "sl": plan["invalidation"],
        "tp": tp,
        "tp_levels": tp_levels,
        "tp_shares": execution.get("tp_shares", []),
        "scale_in_levels": execution.get("scale_in_levels", []),
    }


def _reanchor_blueprint(bp: dict, price: float, atr: float, min_rr: float | None = None) -> dict:
    """Re-anchor SL/TP around the live price for aggressive (late) entries.

    When price has already run past the plan zones, the structural invalidation
    is far and the first TP is close, so RR collapses (poor_rr / invalid_geometry
    blockers). Tighten the stop to ~2 ATR and pick the furthest valid target so
    the trade keeps sane geometry; if nothing works, mark the blueprint blocked.

    b54: min_rr None-resolved at CALL time (a default bound at def-time would
    make the sweep's monkeypatch of REANCHOR_MIN_RR a silent no-op).
    """
    if min_rr is None:
        min_rr = REANCHOR_MIN_RR
    atr = float(atr or 0) or 5.0
    side = bp["side"]
    sl = float(bp["sl"])
    stop_dist_cap = REANCHOR_STOP_ATR_CAP * atr

    if side == "SELL":
        # stop must sit above entry: min(structural invalidation, price + 2*ATR)
        sl = min(sl, price + stop_dist_cap) if sl > price else price + stop_dist_cap
        sl = max(sl, price + 0.5 * atr)  # never tighter than half an ATR
        stop_dist = sl - price
        cands = [t for t in bp.get("tp_levels") or [] if t < price]
        tp = max(cands, key=lambda t: (price - t) / stop_dist) if cands else None
        if tp is None or (price - tp) / stop_dist < min_rr:
            tp = price - stop_dist * min_rr
    else:
        sl = max(sl, price - stop_dist_cap) if sl < price else price - stop_dist_cap
        sl = min(sl, price - 0.5 * atr)
        stop_dist = price - sl
        cands = [t for t in bp.get("tp_levels") or [] if t > price]
        tp = min(cands, key=lambda t: (t - price) / stop_dist) if cands else None
        if tp is None or (tp - price) / stop_dist < min_rr:
            tp = price + stop_dist * min_rr

    bp = dict(bp)
    bp["sl"] = round(sl, 2)
    # Parity with auto_executor Check 5.6: the executor recomputes RR from the
    # ROUNDED sl/tp. Naive rounding of tp = price + 1.5*stop can land at
    # RR 1.4997 and the gate kills the trade this function just built
    # (measured: 28/51 live-parity entries died as poor_rr_1.50).
    # Pad the target to min_rr + 0.05 AFTER rounding so geometry always clears
    # the floor with margin.
    _sd = abs(price - bp["sl"])
    _tp = round(tp, 2)
    if _sd > 0:
        _need = price - _sd * (min_rr + 0.05) if side == "SELL" else price + _sd * (min_rr + 0.05)
        _tp = min(_tp, _need) if side == "SELL" else max(_tp, _need)
    bp["tp"] = round(_tp, 2)
    bp["tp_levels"] = [round(_tp, 2)]
    bp["tp_shares"] = [1.0]
    bp["reanchored"] = True
    return bp


def _buy_logic(plan: dict, price: float, trigger_ok: bool, now: datetime) -> dict:
    zones = plan["zones"]
    execution = plan.get("execution", {})
    breakout_trigger = execution.get("breakout_trigger", zones["short_entry_low"])

    if zones["long_entry_low"] <= price <= zones["long_entry_high"]:
        if trigger_ok:
            bp = build_trade_blueprint(plan, price=price, trigger_ok=trigger_ok)
            bp = _reanchor_blueprint(
                bp, price, float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
            )
            return {
                "action": "market_entry_now",
                "zone": "long_zone",
                "execution_style": "pullback_continuation",
                "blueprint": bp,
                "at": now.isoformat(),
            }
        return {
            "action": "wait_for_trigger",
            "zone": "long_zone",
            "execution_style": "pullback_wait",
            "at": now.isoformat(),
        }

    if price < zones["long_entry_low"]:
        return {
            "action": "place_buy_limit",
            "zone": "discount",
            "entry_price": zones["long_entry_low"],
            "execution_style": "pullback_limit",
            "at": now.isoformat(),
        }

    if price >= zones["value_high"] and plan.get("bias") == "bullish":
        # Aggressive premium entry — only when close to zone
        atr_val = float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
        dist_above = price - zones["value_high"]
        if dist_above > atr_val * 1.5:
            return {
                "action": "no_trade",
                "reason": "price_far_above_zone_plan_stale",
                "zone": "premium",
                "execution_style": "wait_for_replan",
                "at": now.isoformat(),
            }
        smc_conf = plan.get("quality", {}).get("smc_confidence", 0) or 0
        if smc_conf >= SMC_CONF_FLOOR:
            # Re-anchor the blueprint to current market conditions, otherwise the
            # stale plan TP (far above after a long move) breaks trade geometry.
            bp = build_trade_blueprint(plan, price=price, trigger_ok=True)
            bp = _reanchor_blueprint(bp, price, atr_val)
            return {
                "action": "market_entry_now",
                "zone": "premium",
                "execution_style": "aggressive_premium_entry",
                "blueprint": bp,
                "at": now.isoformat(),
            }
    if price <= zones["value_high"]:
        # Aggressive: in premium zone with strong bullish bias, enter long
        near_value_high = abs(price - zones["value_high"]) < (zones["value_high"] - zones["value_low"]) * 0.3
        if near_value_high and plan.get("bias") == "bullish":
            smc_conf = plan.get("quality", {}).get("smc_confidence", 0) or 0
            if smc_conf >= SMC_CONF_FLOOR:
                bp = build_trade_blueprint(plan, price=price, trigger_ok=True)
                bp = _reanchor_blueprint(
                    bp, price, float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
                )
                return {
                    "action": "market_entry_now",
                    "zone": "value_zone",
                    "execution_style": "aggressive_value_entry",
                    "blueprint": bp,
                    "at": now.isoformat(),
                }
        return {
            "action": "no_trade",
            "reason": "outside_entry_zones",
            "zone": classify_price_location(price, zones),
            "execution_style": "hold_bias_wait_better_price",
            "at": now.isoformat(),
        }

    if price <= zones["short_entry_high"]:
        return {
            "action": "place_buy_stop",
            "zone": classify_price_location(price, zones),
            "entry_price": breakout_trigger,
            "execution_style": "breakout_continuation",
            "at": now.isoformat(),
        }

    return {
        "action": "wait_for_pullback",
        "reason": "price_extended_above_breakout_zone",
        "zone": "premium",
        "execution_style": "extended_wait",
        "at": now.isoformat(),
    }


def _sell_logic(plan: dict, price: float, trigger_ok: bool, now: datetime) -> dict:
    zones = plan["zones"]
    execution = plan.get("execution", {})
    breakout_trigger = execution.get("breakout_trigger", zones["long_entry_high"])

    if zones["short_entry_low"] <= price <= zones["short_entry_high"]:
        if trigger_ok:
            bp = build_trade_blueprint(plan, price=price, trigger_ok=trigger_ok)
            bp = _reanchor_blueprint(
                bp, price, float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
            )
            return {
                "action": "market_entry_now",
                "zone": "short_zone",
                "execution_style": "pullback_continuation",
                "blueprint": bp,
                "at": now.isoformat(),
            }
        return {
            "action": "wait_for_trigger",
            "zone": "short_zone",
            "execution_style": "pullback_wait",
            "at": now.isoformat(),
        }

    if price > zones["short_entry_high"]:
        return {
            "action": "place_sell_limit",
            "zone": "premium",
            "entry_price": zones["short_entry_high"],
            "execution_style": "pullback_limit",
            "at": now.isoformat(),
        }

    if price >= breakout_trigger:
        # Aggressive: if price is near value_low and trending, allow entry
        near_value_low = abs(price - zones["value_low"]) < (zones["value_high"] - zones["value_low"]) * 0.3
        if near_value_low and plan.get("quality", {}).get("smc_confidence", 0) >= SMC_CONF_FLOOR:
            bp = build_trade_blueprint(plan, price=price, trigger_ok=True)
            bp = _reanchor_blueprint(
                bp, price, float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
            )
            return {
                "action": "market_entry_now",
                "zone": "value_zone",
                "execution_style": "aggressive_value_entry",
                "blueprint": bp,
                "at": now.isoformat(),
            }
        return {
            "action": "wait_for_pullback",
            "reason": "inside_value_without_trigger",
            "zone": classify_price_location(price, zones),
            "execution_style": "hold_bias_wait_better_price",
            "at": now.isoformat(),
        }

    # Aggressive: in discount zone with strong bearish bias, enter short
    # BUT only if price is close to the zone (not 100+ points away = stale plan)
    if price < zones["value_low"] and plan.get("bias") == "bearish":
        smc_conf = plan.get("quality", {}).get("smc_confidence", 0) or 0
        atr_val = float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
        dist_below = zones["value_low"] - price
        if dist_below > atr_val * 1.5:
            return {
                "action": "no_trade",
                "reason": "price_far_below_zone_plan_stale",
                "zone": "discount",
                "execution_style": "wait_for_replan",
                "at": now.isoformat(),
            }
        if smc_conf >= SMC_CONF_FLOOR:
            # Re-anchor the blueprint to current market conditions, otherwise the
            # stale plan TP (far below after a long move) breaks trade geometry.
            bp = build_trade_blueprint(plan, price=price, trigger_ok=True)
            bp = _reanchor_blueprint(
                bp, price, float(plan.get("atr") or plan.get("quality", {}).get("atr") or 20)
            )
            return {
                "action": "market_entry_now",
                "zone": "discount",
                "execution_style": "aggressive_discount_entry",
                "blueprint": bp,
                "at": now.isoformat(),
            }
        return {
            "action": "wait_for_pullback",
            "reason": "discount_zone_with_weak_smc",
            "zone": classify_price_location(price, zones),
            "execution_style": "extended_wait",
            "at": now.isoformat(),
        }

    if price >= zones["long_entry_low"]:
        return {
            "action": "place_sell_stop",
            "zone": classify_price_location(price, zones),
            "entry_price": breakout_trigger,
            "execution_style": "breakout_continuation",
            "at": now.isoformat(),
        }

    return {
        "action": "wait_for_pullback",
        "reason": "price_extended_below_breakout_zone",
        "zone": "discount",
        "execution_style": "extended_wait",
        "at": now.isoformat(),
    }


def decide_execution_action(plan: dict, price: float, trigger_ok: bool, now: datetime) -> dict:
    # A neutral plan is an explicit no-trade state.  Never route it through
    # the bearish branch below; that could produce sell-stop/limit proposals.
    if plan.get("bias") == "neutral":
        return {
            "action": "no_trade",
            "reason": "neutral_bias",
            "zone": classify_price_location(price, plan["zones"]),
            "at": now.isoformat(),
        }
    execution = plan.get("execution") or {}
    if not execution:
        zone = classify_price_location(price, plan["zones"])
        if zone not in {"long_zone", "short_zone"}:
            return {
                "action": "no_trade",
                "reason": "outside_entry_zones",
                "zone": zone,
                "at": now.isoformat(),
            }
        if not trigger_ok:
            return {
                "action": "wait_for_trigger",
                "zone": zone,
                "at": now.isoformat(),
            }
        return {
            "action": "market_order",
            "zone": zone,
            "blueprint": build_trade_blueprint(plan, price=price, trigger_ok=trigger_ok),
            "at": now.isoformat(),
        }

    if plan.get("bias") == "bullish":
        return _buy_logic(plan, price=price, trigger_ok=trigger_ok, now=now)
    return _sell_logic(plan, price=price, trigger_ok=trigger_ok, now=now)
