"""Signal Decision Engine — evaluates a parsed signal against Hermes' own analysis.

Checks:
1. Signal confidence (parser quality)
2. Symbol match (is it XAUUSD or something we trade?)
3. Direction alignment with Hermes bias
4. Risk/Reward ratio
5. Drawdown / account policy
6. News blackout
7. Session timing
"""
from __future__ import annotations

from datetime import datetime, timezone


def evaluate_signal(signal: dict, hermes_analysis: dict, account_policy: dict, macro_filter: dict | None = None, now: datetime | None = None) -> dict:
    """Evaluate a parsed signal against Hermes' analysis.

    Args:
        signal: Parsed signal dict from signal_parser.Signal.to_dict()
        hermes_analysis: Current plan dict (from hermes_runtime)
        account_policy: Account policy dict (from risk.assess_account_policy)
        macro_filter: Macro filter result dict
        now: Current datetime

    Returns:
        dict with verdict, reasons, and recommended action
    """
    now = now or datetime.now(timezone.utc)
    reasons = []
    score = 0.0
    max_score = 10.0

    symbol = signal.get("symbol", "")
    side = signal.get("side", "").upper()
    confidence = signal.get("confidence", 0)
    rr = signal.get("rr_ratio", 0) or signal.get("computed_rr", 0)
    entry = signal.get("entry", 0)
    sl = signal.get("sl", 0)
    warnings = signal.get("warnings", [])

    # ── Check 1: Symbol (must be XAUUSD) ──
    if symbol != "XAUUSD":
        reasons.append(f"unsupported_symbol:{symbol}")
        return {
            "verdict": "skip",
            "reason": reasons[-1],
            "reasons": reasons,
            "score": 0,
            "max_score": max_score,
            "trade_allowed": False,
        }

    score += 1.0

    # ── Check 2: Signal quality / confidence ──
    if confidence < 0.3:
        reasons.append("low_signal_confidence")
        return {
            "verdict": "skip",
            "reason": reasons[0],
            "reasons": reasons,
            "score": score,
            "max_score": max_score,
            "trade_allowed": False,
        }
    elif confidence >= 0.7:
        score += 2.0
        reasons.append("high_confidence")
    else:
        score += 1.0
        reasons.append("medium_confidence")

    # ── Check 3: Direction validity ──
    if side not in {"BUY", "SELL"}:
        reasons.append("invalid_direction")
        return {
            "verdict": "skip",
            "reason": reasons[0],
            "reasons": reasons,
            "score": score,
            "max_score": max_score,
            "trade_allowed": False,
        }
    score += 1.0

    # ── Check 4: Direction alignment with Hermes bias ──
    # b163: the caller's plan bias is UNBOUNDED in age by contract (storage
    # has no expiry filter here). Census scripts/b163_plan_age_census.py
    # (data/backtest/b163_plan_age_census.json) joined all 52 logged
    # decisions to the plan timeline: every joinable one scored a plan
    # <=0.28h old, zero past the 12h expires_at, zero decisive-from-stale —
    # so the +/- stays as-is (KEEP+PIN, b158 shape) and the caller now
    # records the plan age with each decision (signal_listener.plan_age_hours).
    hermes_bias = hermes_analysis.get("bias", "neutral")
    # Normalize: "bullish" -> "BUY", "bearish" -> "SELL"
    bias_to_side = {"bullish": "BUY", "bearish": "SELL", "neutral": "NEUTRAL"}
    normalized_bias = bias_to_side.get(hermes_bias, hermes_bias.upper())
    if normalized_bias == "NEUTRAL" or hermes_bias == "neutral":
        reasons.append("hermes_neutral")
        score += 0.5
    elif side == normalized_bias:
        score += 2.0
        reasons.append("direction_aligned")
    else:
        score -= 1.0
        reasons.append("direction_conflict")
        reasons.append(f"hermes_says_{hermes_bias}_signal_says_{side.lower()}")

    # ── Check 5: Risk/Reward ──
    if rr > 0:
        if rr >= 2.0:
            score += 1.5
            reasons.append(f"excellent_rr_{rr}")
        elif rr >= 1.5:
            score += 1.0
            reasons.append(f"good_rr_{rr}")
        elif rr >= 1.0:
            score += 0.5
            reasons.append(f"acceptable_rr_{rr}")
        else:
            score -= 1.0
            reasons.append(f"poor_rr_{rr}")
    elif sl > 0 and entry > 0:
        # Compute from entry/SL
        if signal.get("tp", 0) > 0:
            risk = abs(entry - sl)
            reward = abs(signal["tp"] - entry)
            computed_rr = reward / risk if risk > 0 else 0
            if computed_rr >= 2.0:
                score += 1.5
                reasons.append(f"computed_rr_{computed_rr}")
            elif computed_rr >= 1.0:
                score += 0.5
            else:
                reasons.append("poor_computed_rr")
        else:
            reasons.append("no_tp_for_rr")
    else:
        reasons.append("missing_sl")
        score -= 0.5

    # ── Check 6: Account policy ──
    if not account_policy.get("trade_allowed", True):
        reasons.append(f"account_locked:{account_policy.get('regime')}")
        score -= 5.0
    elif account_policy.get("open_positions", 0) > 0:
        reasons.append("already_in_position")
        score -= 0.5

    # ── Check 7: Macro / news filter ──
    # b30 HARD BLOCK: this used to be a -2.0 score penalty, and a
    # high-confidence aligned signal (7.5) still executed straight through a
    # FOMC blackout. The plan path (apply_macro_guard) blocks outright — the
    # signal path now matches. An unavailable calendar also lands here
    # (evaluate_macro_filter fails closed), so no news visibility = no trade.
    if macro_filter and not macro_filter.get("allowed", True):
        reasons.append(macro_filter.get("reason") or "news_blackout")
        return {
            "verdict": "skip",
            # b165: SAME expression as the append above — the old
            # .get("reason", "news_blackout") disagreed with the list when
            # the key existed but was empty ("" headline vs
            # "news_blackout" in reasons), breaking the contract that the
            # singular headline is always a member of the plural list.
            "reason": reasons[-1],
            "reasons": reasons,
            "score": round(min(max_score, max(0, score)), 2),
            "max_score": max_score,
            "trade_allowed": False,
        }

    # ── Check 8: Warnings from parser ──
    for w in warnings:
        if "sl_" in w:
            score -= 0.5
            reasons.append(f"parser:{w}")

    # ── Verdict ── (fully autonomous: execute or skip, never "ask the user")
    final_score = round(min(max_score, max(0, score)), 2)
    if final_score >= 6.0 and account_policy.get("trade_allowed", False):
        verdict = "execute"
    else:
        verdict = "skip"

    # Never auto-execute without SL
    if verdict == "execute" and sl <= 0:
        verdict = "skip"
        reasons.append("no_sl_critical")

    return {
        "verdict": verdict,
        "reasons": reasons,
        "score": final_score,
        "max_score": max_score,
        "trade_allowed": verdict == "execute",
        "signal": signal,
    }
