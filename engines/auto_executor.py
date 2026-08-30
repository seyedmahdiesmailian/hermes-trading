"""Auto Executor — autonomous trade execution engine.

This module makes trade execution decisions like a professional trader:
- Evaluates proposals against risk rules
- Calculates position size based on account state
- Executes trades automatically when conditions are met
- Manages existing positions (TP, SL, breakeven, partial close)

NO human approval required. The system decides and acts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from engines.orchestrator import compute_xau_position_size
from engines.market_hours import is_market_open
from engines.defcon import filter_management_by_insights


# ─── Risk Parameters (professional trader defaults) ───
MAX_RISK_PER_TRADE_PCT = 0.02       # 2% of balance per trade
MIN_RISK_REWARD = 1.5             # skip trades with RR below this (backtest 2026-08-29: RR2 vs RR3 identical on 500 bars → 1.5 floor keeps entries healthy without inflating targets)
MAX_DAILY_LOSS_PCT = 0.05           # 5% daily loss → stop trading
MAX_DAILY_TRADES = 5                # max trades per day
MAX_OPEN_POSITIONS = 2              # max simultaneous positions
MIN_SETUP_GRADE = "B"               # backtest 2026-08-29: C-grade (weak trend) entries drag win-rate; B keeps 13-trade sample with 61.5% WR
STOP_TRADING_REGIMES = {"locked"}   # regimes that block new trades
TIGHT_REGIMES = {"defensive"}       # reduced sizing regimes


def _now() -> datetime:
    return datetime.now(timezone.utc)


def evaluate_proposal(
    proposal: dict,
    account_policy: dict,
    performance_state: dict,
    plan: dict,
    bridge=None,
) -> dict:
    """Evaluate a trade proposal and decide: execute or skip.

    This is the brain of autonomous trading. It checks:
    1. Is the proposal valid?
    2. Is the account allowed to trade?
    3. Is the daily loss limit respected?
    4. Is the daily trade count within limits?
    5. Is the setup grade good enough?
    6. Is the risk/reward acceptable?
    7. Calculate position size
    8. Return execution command or skip reason
    """
    now = _now()
    reasons = []
    skip = False

    # ── Adaptive learning parameters (Phase 6) ──
    # learning_state.json holds params auto-adjusted from the trade journal.
    # Learning can only TIGHTEN (raise RR floor / grade / lower risk) or gently
    # relax risk within hard clamps defined in engines/learning.py.
    try:
        from engines.learning import load_learning_state
        _ls = load_learning_state()
    except Exception:
        _ls = {}
    _eff_min_rr = float(_ls.get("min_rr", MIN_RISK_REWARD))

    # ── Check 1: Valid proposal ──
    if not proposal or proposal.get("blocked"):
        return {
            "execute": False,
            "reason": proposal.get("reason", "no_proposal") if proposal else "no_proposal",
            "command": None,
        }

    blueprint = proposal.get("blueprint")
    if not blueprint:
        return {
            "execute": False,
            "reason": "no_blueprint",
            "command": None,
        }

    side = str(blueprint.get("side", "")).upper()
    entry = float(blueprint.get("entry_price", 0))
    sl = float(blueprint.get("sl", 0))
    tp = float(blueprint.get("tp", 0))
    symbol = blueprint.get("symbol", "XAUUSD")

    if side not in {"BUY", "SELL"} or entry <= 0 or sl <= 0 or tp <= 0:
        return {
            "execute": False,
            "reason": "invalid_blueprint",
            "command": None,
        }

    # ── Check 2: Account policy ──
    regime = account_policy.get("regime", "normal")
    trade_allowed = account_policy.get("trade_allowed", True)

    if not trade_allowed or regime in STOP_TRADING_REGIMES:
        reasons.append(f"account_{regime}")
        return {
            "execute": False,
            "reason": f"account_policy_{regime}",
            "command": None,
            "reasons": reasons,
        }

    # ── Check 3: Daily loss limit ──
    daily_pnl = float(performance_state.get("daily_pnl", 0) or 0)
    balance = float(account_policy.get("balance", 0) or 0)
    if balance > 0:
        daily_loss_pct = abs(min(0, daily_pnl)) / balance
        if daily_loss_pct >= MAX_DAILY_LOSS_PCT:
            reasons.append(f"daily_loss_{daily_loss_pct:.1%}")
            return {
                "execute": False,
                "reason": "daily_loss_limit",
                "command": None,
                "reasons": reasons,
            }

    # ── Check 4: Daily trade count ──
    trades_today = int(performance_state.get("trades_today", 0) or 0)
    if trades_today >= MAX_DAILY_TRADES:
        reasons.append(f"max_daily_trades_{trades_today}")
        return {
            "execute": False,
            "reason": "daily_trade_limit",
            "command": None,
            "reasons": reasons,
        }

    # ── Check 5: Open positions limit ──
    open_positions = int(account_policy.get("open_positions", 0) or 0)
    if open_positions >= MAX_OPEN_POSITIONS:
        reasons.append(f"max_positions_{open_positions}")
        return {
            "execute": False,
            "reason": "position_limit",
            "command": None,
            "reasons": reasons,
        }

    # ── Check 5.5: TP/SL sanity (broker rejects invalid geometry) ──
    if side == "SELL" and (tp >= entry or sl <= entry):
        reasons.append("invalid_geometry_sell")
        return {"execute": False, "reason": "invalid_geometry", "command": None, "reasons": reasons}
    if side == "BUY" and (tp <= entry or sl >= entry):
        reasons.append("invalid_geometry_buy")
        return {"execute": False, "reason": "invalid_geometry", "command": None, "reasons": reasons}

    # ── Check 5.6: Risk:Reward floor (never risk $1 to make $0.15) ──
    _sl_dist = abs(entry - sl)
    _tp_dist = abs(tp - entry)
    if _sl_dist > 0:
        _rr = _tp_dist / _sl_dist
        if _rr < max(MIN_RISK_REWARD, _eff_min_rr):
            reasons.append(f"poor_rr_{_rr:.2f}")
            return {
                "execute": False,
                "reason": f"poor_rr_{_rr:.2f}",
                "command": None,
                "reasons": reasons,
            }

    # ── Check 6: Setup grade ──
    grade = _infer_setup_grade(plan)
    if grade > MIN_SETUP_GRADE:  # A < B < C in string order, but A is best grade
        reasons.append(f"grade_{grade}_below_minimum")
        return {
            "execute": False,
            "reason": f"setup_grade_{grade}",
            "command": None,
            "reasons": reasons,
        }

    # ── Check 6.5: Adaptive learning grade gate (Phase 6) ──
    try:
        from engines.learning import GRADES
        _grade_idx = GRADES.index(grade)
        if _grade_idx < GRADES.index(str(_ls.get("min_grade", "B"))):
            reasons.append(f"learned_grade_{_ls.get('min_grade')}")
            return {
                "execute": False,
                "reason": f"learned_min_grade_{_ls.get('min_grade')}",
                "command": None,
                "reasons": reasons,
            }
    except Exception:
        pass

    # ── Check 6.6: DEFCON (legacy closed-trade feedback loop) ──
    # GREEN full risk / YELLOW half risk, no runner / RED no new entries.
    _defcon_insights = None
    try:
        from engines.defcon import compute_insights, classify_exits
        _deals = performance_state.get("recent_closed") or []
        _defcon_insights = compute_insights(
            loss_streak=int(performance_state.get("loss_streak", 0) or 0),
            daily_pnl=float(performance_state.get("daily_pnl", 0) or 0),
            balance=balance,
            classified=classify_exits(_deals),
        )
        if not _defcon_insights.get("trade_allowed", True):
            return {
                "execute": False,
                "reason": f"defcon_{str(_defcon_insights.get('defcon')).lower()}_entry_blocked",
                "command": None,
                "reasons": reasons + [f"defcon_{_defcon_insights.get('defcon')}"],
                "defcon": _defcon_insights.get("defcon"),
            }
    except Exception:
        pass

    # ── Check 6.7: Post-open / restart cooldown (legacy engine_state) ──
    try:
        from engines.cooldown import check_entry_cooldown
        _cd = check_entry_cooldown(now)
        if not _cd.get("allowed"):
            return {
                "execute": False,
                "reason": _cd.get("reason", "cooldown"),
                "command": None,
                "reasons": reasons + [_cd.get("reason")],
                "cooldown_until": _cd.get("until"),
            }
    except Exception:
        pass

    # ── Check 7: Macro/news filter ──
    if proposal.get("blocked_by_macro"):
        reasons.append("macro_blackout")
        return {
            "execute": False,
            "reason": "macro_blackout",
            "command": None,
            "reasons": reasons,
        }

    # ── Check 7.5: Market session window (avoid broker MARKET_CLOSED spam) ──
    # XAUUSD trades ~Sun 23:00 → Fri 22:00 UTC (shared guard, also used by the signal path)
    if not is_market_open():
        reasons.append("market_closed")
        return {
            "execute": False,
            "reason": "market_closed",
            "command": None,
            "reasons": reasons,
        }

    # ── Calculate position size ──
    risk_pct = MAX_RISK_PER_TRADE_PCT * float(_ls.get("risk_mult", 1.0))  # adaptive multiplier (≤1.0)
    # DEFCON YELLOW → half risk (legacy rule); RED never reaches here
    _risk_override = (_defcon_insights or {}).get("risk_override")
    if _risk_override is not None:
        risk_pct *= float(_risk_override)
    if regime in TIGHT_REGIMES:
        risk_pct *= 0.5  # reduce size in defensive mode

    stop_distance = abs(entry - sl)
    # Broker specs (CapitalXtend XAUUSD): point = 0.01 ($0.01 move)
    # 1 lot = 100 oz → 1 point ($0.01) move = $1.00 P/L per 1.0 lot
    point = 0.01
    point_value_per_lot = 1.0

    sizing = compute_xau_position_size(
        balance=balance,
        risk_pct=risk_pct,
        stop_distance_price=stop_distance,
        point=point,
        point_value_per_lot=point_value_per_lot,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=1.0,
        min_meaningful_lot=0.01,
    )

    lot = sizing.get("lot", 0)
    if lot <= 0 or not sizing.get("meaningful"):
        reasons.append(f"sizing_{sizing.get('reason', 'too_small')}")
        return {
            "execute": False,
            "reason": f"sizing_{sizing.get('reason', 'too_small')}",
            "command": None,
            "reasons": reasons,
            "sizing": sizing,
        }

    # ── Build execution command ──
    # Calculate SL and TP in points for MT5
    sl_points = int(round(stop_distance / point))
    tp_distance = abs(tp - entry)
    tp_points = int(round(tp_distance / point))

    command = {
        "side": side,
        "lot": lot,
        "symbol": symbol,
        "sl_points": sl_points,
        "tp_points": tp_points,
        "entry": entry,
        "sl": sl,
        "tp": tp,
    }

    return {
        "execute": True,
        "reason": "auto_approved",
        "command": command,
        "reasons": reasons,
        "sizing": sizing,
        "grade": grade,
        "risk_pct": risk_pct,
        "risk_usd": sizing.get("risk_usd", 0),
    }


def evaluate_management_action(
    management: dict,
    bridge,
    ticket: int,
    dry_run: bool = False,
    insights: dict | None = None,
) -> dict:
    """Execute a trade management action (TP, SL, breakeven, etc.)

    insights: optional DEFCON insights (engines.defcon.compute_insights).
    When given, filter_management_by_insights() is applied HERE — the single
    choke point both management callers (hermes_runtime, position_daemon)
    funnel through. NO live caller passes it yet: the filter escalates a
    blocked runner to a full close (untested exit policy) — see engines/defcon.py
    module docstring. Passing None = today's behaviour.

    `executed` mirrors the BROKER's acceptance, not our intent: the bridge
    returns {ok:false} (HTTP 400 retcode_*/404/500) when modify/partial/close
    fails. Hardcoding True (the old behaviour, same bug class as b7 on the
    entry side) made callers set breakeven_active/filled_tp_levels after a
    REJECTED SL move — a winning trade left on its original stop while the
    system believed it was protected.
    """
    action = management.get("action", "hold")
    if insights is not None and action != "hold":
        management = filter_management_by_insights(management, insights)
        action = management.get("action", "hold")
    if action == "hold":
        return {"ok": True, "action": "hold", "executed": False, "management": management}

    if dry_run:
        return {"ok": True, "action": action, "dry_run": True, "executed": False,
                "management": management}

    def _wrap(result, extra=None):
        """Mirror broker acceptance; never claim executed on ok:false."""
        ok = isinstance(result, dict) and result.get("ok", False)
        out = {"ok": ok, "action": action, "result": result, "executed": bool(ok),
               "management": management}
        if not ok:
            out["error"] = str((result or {}).get("error") if isinstance(result, dict)
                               else result) or "bridge_no_response"
        if extra:
            out.update(extra)
        return out

    try:
        if action == "partial_take_profit":
            fraction = float(management.get("close_fraction", 0.5))
            percent = int(round(fraction * 100))
            return _wrap(bridge.partial_close(ticket, percent))

        elif action == "move_stop_to_breakeven":
            new_sl = management.get("new_sl")
            return _wrap(bridge.modify_position(ticket, sl=new_sl))

        elif action == "trail_stop":
            new_sl = management.get("new_sl")
            return _wrap(bridge.modify_position(ticket, sl=new_sl))

        elif action in {"close_runner", "close_trade_early"}:
            return _wrap(bridge.close_position(ticket))

        elif action == "scale_in_existing_idea":
            # Scale-in requires new order — skip for safety
            return {"ok": True, "action": "scale_in_skipped", "reason": "scale_in_disabled",
                    "executed": False, "management": management}

        else:
            return {"ok": True, "action": action, "executed": False,
                    "reason": "unknown_action", "management": management}

    except Exception as e:
        return {"ok": False, "action": action, "error": str(e), "executed": False,
                "management": management}


def execute_trade(command: dict, bridge, dry_run: bool = False) -> dict:
    """Send a trade order to MT5 via bridge.
    
    command contains both 'sl'/'tp' (actual prices) and 'sl_points'/'tp_points'.
    The bridge expects actual price levels for SL/TP.

    This is the LAST line of defense: every path (plan-driven, signal-driven,
    manual) funnels through here, so the market-hours gate lives here too.
    """
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_execute": command,
            "executed": False,
        }

    # Final market-hours gate — protects ALL callers, not just evaluate_proposal.
    if not is_market_open():
        return {
            "ok": False,
            "error": "market_closed",
            "command": command,
            "executed": False,
        }

    try:
        side = command["side"]
        lot = command["lot"]
        symbol = command.get("symbol", "XAUUSD")
        # Send actual price levels to bridge (NOT points)
        sl_price = command.get("sl")
        tp_price = command.get("tp")

        result = bridge.send_order(
            side=side,
            lot=lot,
            symbol=symbol,
            sl=sl_price,
            tp=tp_price,
        )

        _accepted = isinstance(result, dict) and result.get("ok", False)
        return {
            "ok": _accepted,
            "result": result,
            "command": command,
            # executed must mean "broker accepted the order". It was hardcoded
            # True whenever send_order returned at all — a retcode 10018/20004
            # rejection still reported "✅ trade opened" to Telegram and the
            # signal listener propagated the lie.
            "executed": _accepted,
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "command": command,
            "executed": False,
        }


def _infer_setup_grade(plan: dict) -> str:
    """Infer setup grade from plan quality."""
    q = plan.get("quality", {})
    alignment = q.get("alignment")
    trend = float(q.get("trend_strength", 0) or 0)
    regime = q.get("regime")
    if alignment == "aligned" and trend >= 3.0 and regime in {"breakout_continuation", "pullback_continuation"}:
        return "A"
    if alignment in {"aligned", "mixed"} and trend >= 1.2:
        return "B"
    return "C"
