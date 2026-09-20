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
from engines.plan import setup_grade, MIN_SETUP_GRADE  # b79d: threshold lives
from engines.market_hours import is_market_open
from engines.defcon import filter_management_by_insights


# ─── Risk Parameters (professional trader defaults) ───
MAX_RISK_PER_TRADE_PCT = 0.02       # 2% of balance per trade
MIN_RISK_REWARD = 1.5             # skip trades with RR below this (backtest 2026-08-29: RR2 vs RR3 identical on 500 bars → 1.5 floor keeps entries healthy without inflating targets)
MAX_DAILY_LOSS_PCT = 0.05           # 5% daily loss → stop trading
MAX_DAILY_TRADES = 5                # max trades per day
MAX_OPEN_POSITIONS = 1              # max simultaneous positions. Was 2 — a
                                    # silent divergence: risk.assess_account_policy
                                    # says max_positions_allowed=1, the parity
                                    # backtest models ONE position at a time, and
                                    # the grade-B audit (b14) justified MIN_SETUP_GRADE
                                    # on the single-slot constraint. Live now matches
                                    # both (tightening only, never loosening).
# b79d: MIN_SETUP_GRADE is IMPORTED from engines.plan above (re-export for
# the entry gate, tests and lab_harness) — the value lives next to
# setup_grade so the monitor gate and Check 6 cannot carry two literals
# that drift. Do not rebind it here: the imported name IS the gate.
# b53: per-entry-style risk multiplier (M5 parity backtest, 6500 bars,
# 2026-09-01). aggressive_discount_entry = no-trigger chase of a move that
# already left the zone: WR 52% vs premium 65%, and it produced the two
# worst live losses (-105$ #103649120, -94$ #103506741). Deleting the lane
# costs ~280$ of 3-week PnL (it is still net positive), so the professional
# answer is HALF SIZE, not removal. Styles not listed keep full risk.
STYLE_RISK_MULT = {
    "aggressive_discount_entry": 0.5,
    "aggressive_value_entry": 0.5,
}
# Session prior (learning.py promised "session-aware later" and never
# wired it). 16/29 live entries fired 00-07 UTC; 5 of 8 fat losses
# (#103649120 -106, #104292973 -104, #104905967 -100, #105127383 -89,
# #105443817 -45) opened in that window. Half size, never a skip —
# Sep 3 Asia still printed +70/+71 winners. Missing/unknown session = 1.0.
SESSION_RISK_MULT = {
    "asia": 0.5,
    "london": 1.0,
    "newyork": 1.0,
}
# Hard lot ceiling. The same four disasters sized 0.15-0.17 because a ~6$
# stop + 2% of ~5k → huge leverage on noise. 0.10 is still 2% of 5k at a
# 10$ stop; anything tighter now risks LESS dollars, never more.
MAX_LOT = 0.10
# Gold noise floor. Joined execution_log→journal: every stop < $8 on the
# 5k book netted −$327 (the four −100$ disasters were 5.84–6.54). Skip
# those entries rather than size them. Below MIN_STOP_BALANCE the b196
# 5pt/1% path must still print 0.01 lot — a small account has no other
# way to clear min_meaningful_lot.
MIN_STOP_DISTANCE = 8.0
MIN_STOP_BALANCE = 1500.0
STOP_TRADING_REGIMES = {"locked"}   # regimes that block new trades
# b136: "recovery" was MISSING here. engines/risk.assess_account_policy emits
# four regimes and hands back a risk_multiplier, but the entry path never reads
# that field — it gates sizing off this set alone (see Check 6 sizing below).
# So the account-health policy's most cautious tradeable state (drawdown >= 2.5%)
# was sizing entries at FULL risk, i.e. larger than "defensive". Adding it is a
# strict TIGHTENING (0.5x, matching the policy's own 0.5 multiplier), never a
# loosening. scripts/b136_regime_wiring_census.py re-derives the set from the
# policy emitter and fails loudly if a future regime is born unwired again.
TIGHT_REGIMES = {"defensive", "recovery"}   # reduced sizing regimes


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
    # b170: these three early returns shipped without 'reasons' — the key
    # hermes_runtime copies into proposal['skip_reasons'] (line ~770) and
    # signal_listener concatenates into the alert (line ~611), exactly the
    # b165 defect class one module over. The verdict/reason strings are
    # byte-identical; only the plural carrier is added (observability, never
    # a gate change).
    if not proposal or proposal.get("blocked"):
        _r = (proposal or {}).get("reason") or "no_proposal"
        return {
            "execute": False,
            "reason": _r,
            "command": None,
            "reasons": [_r],
        }

    blueprint = proposal.get("blueprint")
    if not blueprint:
        return {
            "execute": False,
            "reason": "no_blueprint",
            "command": None,
            "reasons": ["no_blueprint"],
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
            "reasons": ["invalid_blueprint"],
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

    # ── Check 2.5: closed-trade history must be readable ──
    # Missing key = legacy/test callers (unchanged). Explicit False is the
    # 401/MT5-error shape: an empty window used to look like a clean day.
    if account_policy.get("history_ok") is False:
        reasons.append("history_unavailable")
        return {
            "execute": False,
            "reason": "history_unavailable",
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

    # ── Check 5.65: gold noise floor (see MIN_STOP_DISTANCE) ──
    if _sl_dist < MIN_STOP_DISTANCE and balance >= MIN_STOP_BALANCE:
        reasons.append(f"stop_too_tight_{_sl_dist:.2f}")
        return {
            "execute": False,
            "reason": "stop_too_tight",
            "command": None,
            "reasons": reasons,
        }

    # ── Check 6: Setup grade ──
    # The signal path supplies its own quality verdict (the 8-check scorer in
    # signal_decision) via proposal['grade']; the plan path leaves it unset
    # and the grade is inferred from plan quality as before.
    grade = str(proposal.get("grade") or "").upper() or _infer_setup_grade(plan)
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
    except Exception as e:
        # b29 FAIL-CLOSED: grade gate error blocks entry, never bypasses it.
        return {"execute": False, "reason": "learning_gate_error",
                "command": None, "reasons": reasons + [f"learning_error:{e}"]}

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
    except Exception as e:
        # b29 FAIL-CLOSED: a broken safety gate must never let a trade through.
        return {"execute": False, "reason": "defcon_gate_error",
                "command": None, "reasons": reasons + [f"defcon_error:{e}"]}

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
    except Exception as e:
        # b29 FAIL-CLOSED: cooldown gate error blocks entry, never bypasses it.
        return {"execute": False, "reason": "cooldown_gate_error",
                "command": None, "reasons": reasons + [f"cooldown_error:{e}"]}

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
    # b196 (2026-09-09): the sizer must start from the account's OWN base
    # (engines/risk.assess_account_policy emits the balance-tiered
    # base_risk_pct every cycle) instead of the flat MAX. Before this fix the
    # policy's base had ZERO readers in the executor — the b136
    # "computed/reported/never-wired" class on the BASE leg: at balance
    # >=5000 the policy doc says 1.5% but every entry sized 2% (33% looser).
    # Fail-closed contract: MAX_RISK_PER_TRADE_PCT stays the explicit CEILING
    # (min(policy_base, MAX) — every tier is ≤ MAX, so the fix is
    # tightening-only), and a policy dict without the key (legacy/test
    # callers) falls back to MAX = today's behaviour, never a silent 0.
    _policy_base = account_policy.get("base_risk_pct")
    try:
        _policy_base = float(_policy_base) if _policy_base else 0.0
    except (TypeError, ValueError):
        _policy_base = 0.0
    base_pct = min(_policy_base, MAX_RISK_PER_TRADE_PCT) if _policy_base > 0 \
        else MAX_RISK_PER_TRADE_PCT
    risk_pct = base_pct * float(_ls.get("risk_mult", 1.0))  # adaptive multiplier (≤1.0)
    # b53: per-entry-style risk (see STYLE_RISK_MULT). The style tag comes
    # from the monitor decision via _build_proposal; missing tag = full risk.
    _style_mult = STYLE_RISK_MULT.get(str(proposal.get("execution_style") or ""), 1.0)
    risk_pct *= _style_mult
    _session = str((plan or {}).get("session") or "")
    _sess_mult = SESSION_RISK_MULT.get(_session, 1.0)
    risk_pct *= _sess_mult
    # DEFCON YELLOW → half risk (legacy rule); RED never reaches here
    _risk_override = (_defcon_insights or {}).get("risk_override")
    if _risk_override is not None:
        risk_pct *= float(_risk_override)
    _regime_mult = 0.5 if regime in TIGHT_REGIMES else 1.0
    if _regime_mult != 1.0:
        risk_pct *= _regime_mult  # reduce size in defensive mode
    # b139: the dampers that just multiplied into this lot, captured AT
    # THE SOURCE. execution_log.csv cannot carry them (its header is frozen at
    # 12 columns and engines/storage._append_csv_row only writes a header when
    # the file is new — b142's no-op trap), so the stack rides out on the
    # return dict and the callers write it to the risk_ledger.csv sidecar.
    # Additive key only: no gate, no verdict, no lot changes shape here.
    risk_stack = {
        # b196: the BASE that actually sized this lot — the policy's tiered
        # base when present (clamped), else the MAX fallback. Stays the
        # product-consistent first leg for b139's risk_ledger (test_b139
        # multiplies the stack legs and demands final_risk_pct back), so a
        # ledger row now reveals the true base, not a constant.
        "base_risk_pct": base_pct,
        "learning_risk_mult": float(_ls.get("risk_mult", 1.0)),
        "execution_style": str(proposal.get("execution_style") or ""),
        "style_mult": _style_mult,
        "defcon_override": (None if _risk_override is None
                            else float(_risk_override)),
        "regime": regime,
        "regime_mult": _regime_mult,
        "session": _session,
        "session_mult": _sess_mult,
    }

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
        volume_max=MAX_LOT,
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
        # b139: per-trade audit trail for the shrink stack (see above). The
        # callers persist it to data/xau_plan/risk_ledger.csv.
        "risk_stack": dict(risk_stack, final_risk_pct=risk_pct),
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
            err = (result or {}).get('error') if isinstance(result, dict) else result
            if err in (None, '', 'None'):
                # broker/bridge gave no reason — surface the payload itself
                # so logs/Telegram never show a bare "None"
                err = f'bridge_rejected:{str(result)[:100]}'
            out['error'] = str(err) or 'bridge_no_response'
        if extra:
            out.update(extra)
        return out

    try:
        if action == "partial_take_profit":
            fraction = float(management.get("close_fraction", 0.5))
            if fraction >= 1.0:
                # b55: full exit at TP1 — MT5 rejects a 100% partial close
                # (retcode 10026), so close the ticket outright.
                return _wrap(bridge.close_position(ticket))
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
    """b111: this used to be a SECOND copy of the grade rule (the first lived
    in hermes_runtime.py, a third looser one was inlined in
    position_daemon.build_trade). All three now read engines.plan.setup_grade.
    The name stays because the entry gate and tests call it — it is a thin
    alias, not a redefinition, so it cannot drift again."""
    return setup_grade(plan)
