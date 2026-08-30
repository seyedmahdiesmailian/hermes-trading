#!/usr/bin/env python3
"""Hermes Runtime — fully autonomous trading cycle.

NO human approval required. The system:
1. Analyzes market (SMC + Classic)
2. Builds plan
3. Monitors for entry triggers
4. Executes trades automatically via bridge
5. Manages open positions
6. Reports everything to Telegram
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

from engines.context import build_plan_context
from engines.smc import smc_analyse, merge_smc_with_classic
from engines.orchestrator import build_plan_from_context, route_runtime_step, evaluate_monitor_cycle, compute_xau_position_size
from engines.trade_management import evaluate_trade_management
from engines.risk import assess_account_policy, compute_performance_state
from engines.storage import load_current_plan, save_current_plan, load_runtime_state, save_runtime_state, load_performance_state, save_performance_state, append_execution_log, append_reassessment_log
from engines.report import render_plan_brief, render_reassess_brief, render_monitor_brief, render_management_brief, render_execution_brief
from engines.macro_filter import apply_macro_guard
from engines.auto_executor import evaluate_proposal, execute_trade, evaluate_management_action
from engines.kill_switch import check_kill_switch

from engines import paths as _paths  # state paths resolved at CALL time (test-safe)

BASE_DIR = _paths.get_data_root()
DATA_DIR = BASE_DIR / 'data'
PLAN_DIR = DATA_DIR / 'xau_plan'   # legacy alias; live code uses _plan_dir()


def _plan_dir():
    """Resolve the plan dir at CALL time so tests can redirect the tree."""
    return _paths.plan_dir()

SYMBOL = 'XAUUSD'
TIMEFRAME = 'M5'
# Max ask-bid (in $) to allow a NEW entry. Normal XAUUSD spread here is ~0.18;
# news/rollover spikes can blow past 2.0. Backtests charge a flat 0.20 cost,
# so live must not enter when the real cost is multiples of that.
MAX_ENTRY_SPREAD = float(os.getenv('HERMES_MAX_SPREAD', '0.60'))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _detect_session(now: datetime) -> str:
    hour = now.hour
    if 0 <= hour < 7: return 'asia'
    if 7 <= hour < 13: return 'london'
    return 'newyork'


def _data_list(resp: dict) -> list:
    if not isinstance(resp, dict) or not resp.get('ok'):
        return []
    data = resp.get('data', resp.get('rates', resp.get('ohlc', [])))
    return data if isinstance(data, list) else []


def _account_obj(account: dict):
    data = account.get('data', account) if isinstance(account, dict) else {}
    return SimpleNamespace(
        balance=float(data.get('balance', 0) or 0),
        equity=float(data.get('equity', data.get('balance', 0)) or 0),
        margin_free=float(data.get('margin_free', data.get('free_margin', 0)) or 0),
        margin=float(data.get('margin', 0) or 0),
        positions=int(data.get('positions', data.get('positions_total', 0)) or 0),
    )


def _tick_price(tick: dict) -> float:
    data = tick.get('data', tick) if isinstance(tick, dict) else {}
    return float(data.get('ask') or data.get('bid') or data.get('price') or 0)


def _tick_obj(tick: dict):
    data = tick.get('data', tick) if isinstance(tick, dict) else {}
    ask = float(data.get('ask') or data.get('price') or 0)
    bid = float(data.get('bid') or ask or 0)
    return SimpleNamespace(ask=ask, bid=bid)


def _pos_obj(p: dict):
    return SimpleNamespace(
        symbol=p.get('symbol', SYMBOL),
        ticket=int(p.get('ticket', p.get('position_ticket', 0)) or 0),
        type=int(p.get('type', 0) or 0),
        volume=float(p.get('volume', 0) or 0),
        price_open=float(p.get('price_open', p.get('open_price', 0)) or 0),
        sl=float(p.get('sl', 0) or 0),
        tp=float(p.get('tp', 0) or 0),
        time=p.get('time'),  # broker epoch seconds (bridge ≥ v2.1) — feeds time_exit
    )


def _positions_list(resp: dict) -> list:
    if not isinstance(resp, dict) or not resp.get('ok'): return []
    data = resp.get('data', resp.get('positions', []))
    return data if isinstance(data, list) else []


def build_live_plan(bridge, now: datetime | None = None) -> tuple[dict | None, dict | None]:
    now = now or _now()
    session = _detect_session(now)
    m5 = _data_list(bridge.get_rates(SYMBOL, TIMEFRAME, 120))
    h1 = _data_list(bridge.get_rates(SYMBOL, 'H1', 80))
    h4 = _data_list(bridge.get_rates(SYMBOL, 'H4', 80))
    # Right after a bridge/MT5 restart, M5 history may still be syncing — retry once
    if len(m5) < 50:
        import time as _t
        _t.sleep(4)
        m5 = _data_list(bridge.get_rates(SYMBOL, TIMEFRAME, 120))
    if not (m5 and h1 and h4):
        return None, {'ok': False, 'error': 'insufficient_market_data', 'counts': {'M5': len(m5), 'H1': len(h1), 'H4': len(h4)}, 'session': session}
    ctx = build_plan_context(m5, h1, h4, session)
    smc_result = smc_analyse(m5, now=now, h1_rows=h1)
    merged = merge_smc_with_classic(ctx, smc_result)
    classic_regime = ctx.get('quality', {}).get('regime', '')
    smc_confidence = float(merged.get('confidence', 0) or 0)
    smc_bias = merged.get('bias', 'neutral')
    # Only force neutral if SMC is NOT confident AND classic says range
    if classic_regime == 'range' and smc_bias != 'neutral' and smc_confidence < 0.35:
        ctx['bias'] = 'neutral'
        merged['bias'] = 'neutral'
        merged['confidence'] = min(smc_confidence, 0.3)
        merged['action'] = 'wait'
    else:
        # Use SMC bias when confident, even in range
        ctx['bias'] = merged.get('bias', ctx.get('bias'))
    ctx.setdefault('quality', {})['smc_confidence'] = merged.get('confidence')
    ctx['quality']['smc_poi'] = (merged.get('smc_source') or {}).get('poi')
    ctx['quality']['smc_signal'] = (merged.get('smc_source') or {}).get('signal')
    ctx.setdefault('context', {})['smc'] = smc_result
    ctx['context']['merged'] = {k: v for k, v in merged.items() if k != 'smc_result'}
    plan = build_plan_from_context(ctx, now=now)
    return plan, None


def _infer_setup_grade(plan: dict) -> str:
    q = plan.get('quality', {})
    alignment = q.get('alignment')
    trend = float(q.get('trend_strength', 0) or 0)
    regime = q.get('regime')
    if alignment == 'aligned' and trend >= 3.0 and regime in {'breakout_continuation', 'pullback_continuation'}:
        return 'A'
    if alignment in {'aligned', 'mixed'} and trend >= 1.2:
        return 'B'
    return 'C'


def _epoch_to_iso(ts) -> str | None:
    """Bridge position time is broker epoch seconds; legacy_guards wants ISO."""
    try:
        v = float(ts)
        if v > 0:
            return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    return None


def _load_closed_trades(bridge, days=7) -> list[dict]:
    r = bridge.get_history_deals(SYMBOL, days)
    if isinstance(r, dict) and r.get('ok'):
        data = r.get('data', r.get('deals', []))
        return data if isinstance(data, list) else []
    return []


def _performance_and_policy(bridge, account_resp: dict, now: datetime) -> dict:
    account = _account_obj(account_resp)
    today = now.date().isoformat()
    closed = _load_closed_trades(bridge, 7)
    perf = compute_performance_state(load_performance_state(_plan_dir()), today, account.balance, closed)
    save_performance_state(_plan_dir(), perf)
    policy = assess_account_policy(account.balance, account.equity, account.margin_free, account.margin, float(perf.get('daily_pnl', 0) or 0), int(perf.get('loss_streak', 0) or 0), account.positions)
    return {'performance_state': perf, 'account_policy': policy}


def _build_proposal(plan: dict, monitor: dict, policy: dict, tick_price: float) -> dict | None:
    if monitor.get('action') not in {'market_order', 'market_entry_now'}:
        return None
    blueprint = monitor.get('blueprint') or {}
    if not blueprint:
        return None
    # NOTE: macro/calendar guards are applied by the caller; the executor
    # (auto_executor gates 1-13) does the real blocking before any order.
    return {
        'blueprint': blueprint,
        'monitor_action': monitor.get('action'),
        'zone': monitor.get('zone'),
        'price': tick_price,
        'at': datetime.now(timezone.utc).isoformat(),
    }


def cycle(bridge, now: datetime | None = None, dry_run: bool = False, macro_calendar: dict | None = None) -> dict:
    """Main autonomous trading cycle.

    Fully autonomous: this function decides and executes on its own.
    There is no human approval path anywhere in the system.
    """
    now = now or _now()
    runtime = load_runtime_state(_plan_dir())
    old_plan = load_current_plan(_plan_dir())
    step = route_runtime_step(old_plan, now=now)

    account = bridge.get_account()
    tick = bridge.get_tick(SYMBOL)
    positions_resp = bridge.get_positions(SYMBOL)
    positions = _positions_list(positions_resp)
    price = _tick_price(tick)
    acct_policy = _performance_and_policy(bridge, account if isinstance(account, dict) else {}, now)
    performance = acct_policy['performance_state']
    policy = acct_policy['account_policy']

    # ── Kill Switch Check ──
    kill = check_kill_switch(
        balance=policy.get('balance', 0),
        equity=policy.get('equity', 0),
        daily_pnl=float(performance.get('daily_pnl', 0) or 0),
        consecutive_losses=int(performance.get('loss_streak', 0) or 0),
        margin_free=policy.get('margin_free', 0),
        margin=policy.get('margin', 0),
        now=now,
    )

    if kill.get('halted'):
        brief = f"🛑 KILL SWITCH ACTIVE\nReason: {kill.get('reason')}\nResumes: {kill.get('resumes_at')}"
        return {
            'ok': True, 'step': 'halted', 'kill_switch': kill,
            'brief': brief, 'will_execute_now': False,
            'account_policy': policy, 'performance_state': performance,
        }

    # ── Plan / Reassess Step ──
    if step in {'plan', 'reassess'}:
        plan, err = build_live_plan(bridge, now)
        if err:
            return {'ok': False, 'step': step, 'error': err, 'will_execute_now': False}
        save_current_plan(_plan_dir(), plan)
        runtime['active_plan_id'] = plan['plan_id']
        runtime['last_step'] = step
        runtime['last_report_key'] = f"{step}:{plan['plan_id']}"
        save_runtime_state(_plan_dir(), runtime)
        if step == 'reassess' and old_plan:
            append_reassessment_log(_plan_dir(), {'at': now.isoformat(), 'plan_id': plan['plan_id'], 'event': 'reassess', 'old_bias': old_plan.get('bias'), 'new_bias': plan.get('bias')})
            brief = render_reassess_brief(old_plan, plan)
        else:
            brief = render_plan_brief(plan)
        return {'ok': True, 'step': step, 'plan_id': plan['plan_id'], 'plan': plan, 'brief': brief, 'account_policy': policy, 'performance_state': performance, 'will_execute_now': False}

    plan = old_plan
    if not plan:
        return {'ok': False, 'step': 'plan_missing', 'error': 'no_current_plan', 'will_execute_now': False}

    # ── Manage Existing Positions ──
    # Skip if position watchdog daemon is alive (manages every 5s)
    hb = _plan_dir() / 'watchdog_heartbeat'
    watchdog_alive = False
    if hb.exists():
        try:
            age = (now - datetime.fromisoformat(hb.read_text().strip())).total_seconds()
            watchdog_alive = age < 60
        except Exception:
            pass
    if positions and not watchdog_alive:
        tick_obj = _tick_obj(tick if isinstance(tick, dict) else {})
        runtime_state = runtime
        for raw in positions:
            p = _pos_obj(raw)
            trade = {
                'symbol': p.symbol, 'side': 'BUY' if p.type == 0 else 'SELL', 'entry_price': p.price_open,
                'sl': p.sl or plan.get('invalidation') or p.price_open,
                'tp_levels': (plan.get('execution') or {}).get('tp_levels') or plan.get('targets') or [],
                'tp_shares': (plan.get('execution') or {}).get('tp_shares') or [0.5, 0.3, 0.2],
                'scale_in_levels': (plan.get('execution') or {}).get('scale_in_levels') or [],
                'filled_tp_levels': ((runtime_state.get('management') or {}).get(str(p.ticket), {}) or {}).get('filled_tp_levels', []),
                'breakeven_active': bool(((runtime_state.get('management') or {}).get(str(p.ticket), {}) or {}).get('breakeven_active', False)),
                'runner_active': bool(((runtime_state.get('management') or {}).get(str(p.ticket), {}) or {}).get('runner_active', True)),
                'scaled_in_levels': ((runtime_state.get('management') or {}).get(str(p.ticket), {}) or {}).get('scaled_in_levels', []),
                'volume': p.volume, 'regime': (plan.get('quality') or {}).get('regime'), 'setup_grade': _infer_setup_grade(plan),
                'momentum_strength': min(1.0, max(0.2, float((plan.get('quality') or {}).get('trend_strength', 0) or 0) / 2.0)),  # ATR units → 0-1
                'volatility_state': 'high' if float((plan.get('quality') or {}).get('trend_strength', 0) or 0) >= 3.0 else 'normal',
                'structure_state': 'healthy' if (plan.get('quality') or {}).get('alignment') == 'aligned' else 'mixed',
                'session_phase': plan.get('session'), 'rr_remaining': 2.0, 'thesis_valid': (plan.get('quality') or {}).get('alignment') != 'counter', 'exposure_fraction': 0.5,
            }
            market_price = float(tick_obj.ask if trade['side'] == 'BUY' else tick_obj.bid)
            management = evaluate_trade_management(trade, market_price, now)

            # ── Legacy priority merge: news_lock(1) > time_exit(2) > legacy chain(3+) ──
            try:
                from engines.legacy_guards import evaluate_time_exit, evaluate_news_lock
                _cal = plan.get('context', {}).get('macro', {}).get('calendar') if plan.get('context') else None
                _tx = evaluate_time_exit({'opened_at': _epoch_to_iso(getattr(p, 'time', None)), 'side': trade['side']}, now)
                _nl = evaluate_news_lock({**trade, 'side': trade['side'], 'entry_price': getattr(p, 'price_open', market_price), 'sl': getattr(p, 'sl', 0), 'atr': plan.get('atr') or plan.get('quality', {}).get('atr') or 5}, market_price, _cal, now)
                for _guard in (_nl, _tx):
                    if _guard and int(_guard.get('priority', 9)) < int(management.get('priority', 3)):
                        management = _guard
                        break
            except Exception:
                pass

            if management.get('action') != 'hold':
                # AUTO-EXECUTE management action
                # NOTE: DEFCON insights are deliberately NOT passed here.
                # filter_management_by_insights() maps runner-disabled (YELLOW,
                # i.e. loss_streak>=2) to `close_runner` = a FULL market close,
                # so wiring it live would introduce an untested exit policy on a
                # real account. The parity funnel models entries only, never
                # management, so there is no evidence for it. Tracked as a todo.
                mgmt_result = evaluate_management_action(
                    management, bridge, p.ticket, dry_run=dry_run)
                management['position_ticket'] = p.ticket
                management['execution_result'] = mgmt_result

                # Only a broker-accepted action (or a dry-run simulation step)
                # may move our view of the trade. A rejected modify used to be
                # recorded as success → breakeven_active=True while MT5 still
                # held the original stop.
                _committed = bool(mgmt_result.get('executed')) or bool(mgmt_result.get('dry_run'))

                # Update runtime management state
                if management.get('action') == 'partial_take_profit':
                    filled = list(trade.get('filled_tp_levels', []))
                    filled.append(management.get('target_hit'))
                    management['filled_tp_levels'] = filled
                elif management.get('action') == 'move_stop_to_breakeven':
                    management['breakeven_active'] = True
                elif management.get('action') in {'close_runner', 'close_trade_early'}:
                    management['runner_active'] = False

                brief = render_management_brief(plan, management)
                if not _committed and mgmt_result.get('error'):
                    brief += (f"\n\n⚠️ اقدام مدیریت انجام نشد (بروکر رد کرد): "
                              f"{mgmt_result['error'][:120]} — وضعیت قبلی دست‌نخورده")
                # Persist management state (breakeven/filled TPs) — was a bug: not saved
                mgmt_state = runtime.setdefault('management', {})
                tstate = mgmt_state.setdefault(str(p.ticket), {})
                if _committed:
                    if management.get('action') == 'partial_take_profit':
                        tstate['filled_tp_levels'] = management.get('filled_tp_levels', tstate.get('filled_tp_levels', []))
                    elif management.get('action') == 'move_stop_to_breakeven':
                        tstate['breakeven_active'] = True
                    elif management.get('action') in {'close_runner', 'close_trade_early'}:
                        tstate['runner_active'] = False
                save_runtime_state(_plan_dir(), runtime)
                return {'ok': True, 'step': 'manage', 'plan_id': plan.get('plan_id'), 'management': management, 'brief': brief, 'will_execute_now': mgmt_result.get('executed', False), 'account_policy': policy, 'performance_state': performance}

    # ── Monitor for New Entry ──
    monitor = evaluate_monitor_cycle(plan, price=price, now=now)
    # Stale plan (price ran far from zones) → force reassess next cycle
    if 'plan_stale' in str(monitor.get('reason', '')):
        plan['next_reassessment'] = now.isoformat()
        save_current_plan(_plan_dir(), plan)
    proposal = _build_proposal(plan, monitor, policy, price)

    # ── Spread gate: news/rollover spikes blow XAUUSD past 2.0$ (normal 0.18).
    # Cost is linear in trades; entering into a wide spread hands the edge to
    # the broker. Read-only tick check — blocks the PROPOSAL, never management.
    if proposal is not None:
        try:
            _tk = tick if isinstance(tick, dict) else {}
            _td = _tk.get('data', _tk)
            _spr = float(_td.get('ask') or 0) - float(_td.get('bid') or 0)
            if _spr > MAX_ENTRY_SPREAD:
                proposal = None
                monitor['spread_blocked'] = round(_spr, 2)
        except (TypeError, ValueError):
            pass

    if proposal is not None:
        # News blackout on the entry path. hermes_master never passed
        # macro_calendar, so this guard was dead in production — fetch the
        # cached calendar here so EVERY caller is protected (the calendar
        # module caches to disk; this is cheap).
        try:
            from engines.economic_calendar import fetch_economic_calendar
            from engines.macro_filter import evaluate_macro_filter
            cal = (macro_calendar or {}).get('calendar') or fetch_economic_calendar()
            filt = (macro_calendar or {}).get('filter_result') or evaluate_macro_filter(cal, now)
            proposal = apply_macro_guard(proposal, filt)
        except Exception:
            pass

    # ── Legacy migration: macro snapshot into plan context + report ──
    # analyze_macro costs ~22 bridge calls (6 FX ticks + 6 H1 rates + silver/
    # SPX aliases + H4/D1/W1 gold). It feeds REPORTS ONLY — no decision gate
    # reads it — so cache it on disk with a 15-min TTL instead of refetching
    # every 15-min cycle. Calendar is refreshed with the snapshot.
    macro_snap = None
    try:
        import time as _time
        from pathlib import Path as _P
        snap_file = _P(str(_plan_dir())) / 'macro_snapshot.json'
        snap_ttl = 900
        cached = None
        try:
            cached = json.loads(snap_file.read_text(encoding='utf-8'))
        except Exception:
            cached = None
        fresh = cached and (_time.time() - float(cached.get('_fetched_at', 0))) < snap_ttl
        if fresh:
            macro_snap = cached
        else:
            from engines.macro_snapshot import analyze_macro, gold_macro_verdict
            macro_snap = analyze_macro(bridge, SYMBOL)
            macro_snap['verdict'] = gold_macro_verdict(macro_snap)
            # attach the economic calendar so news_lock (legacy_guards) has data —
            # was missing entirely: news_lock read plan.context.macro.calendar which
            # nobody ever wrote → the guard could never fire.
            try:
                from engines.economic_calendar import get_upcoming_events
                macro_snap['calendar'] = get_upcoming_events(hours_ahead=24)
            except Exception:
                macro_snap['calendar'] = None
            macro_snap['_fetched_at'] = _time.time()
            try:
                from engines import paths as _pp
                _pp.write_json_atomic(snap_file, macro_snap)
            except Exception:
                pass
        plan.setdefault('context', {})['macro'] = macro_snap
        save_current_plan(_plan_dir(), plan)   # persist for reports + management
    except Exception:
        macro_snap = None

    execution_result = None
    will_execute = False

    if proposal and not proposal.get('blocked'):
        # AUTO-EXECUTE the trade
        eval_result = evaluate_proposal(proposal, policy, performance, plan, bridge)
        if eval_result.get('execute'):
            cmd = eval_result.get('command')
            if cmd:
                execution_result = execute_trade(cmd, bridge, dry_run=dry_run)
                will_execute = execution_result.get('executed', False)
                proposal['auto_execution'] = eval_result
                proposal['execution_result'] = execution_result
                # Alert hygiene: broker rejected an approved order → surface it
                # in the brief (master sends Telegram on skip_reason). Without
                # this, a rejection after passing ALL gates was silent — the
                # worst kind of failure (we thought we were in a trade).
                if not will_execute and not dry_run:
                    proposal['skip_reason'] = 'broker_rejected: ' + str(
                        (execution_result.get('result') or {}).get('error')
                        or execution_result.get('error') or 'unknown')[:120]

                # Log the execution
                append_execution_log(_plan_dir(), {
                    'at': now.isoformat(),
                    'plan_id': plan.get('plan_id'),
                    'side': cmd.get('side'),
                    'lot': cmd.get('lot'),
                    'entry': cmd.get('entry'),
                    'sl': cmd.get('sl'),
                    'tp': cmd.get('tp'),
                    'grade': eval_result.get('grade'),
                    'risk_usd': eval_result.get('risk_usd'),
                    'dry_run': dry_run,
                    'result_ok': execution_result.get('ok', False),
                    # exact journal→plan linkage (was time-proximity heuristic)
                    'ticket': ((execution_result.get('result') or {}).get('ticket')),
                })
        else:
            proposal['skip_reason'] = eval_result.get('reason')
            proposal['skip_reasons'] = eval_result.get('reasons', [])

    # Build brief
    brief = render_monitor_brief(plan, monitor)
    if will_execute and execution_result:
        brief += "\n\n" + render_execution_brief(plan, execution_result)
    elif proposal and proposal.get('skip_reason'):
        _reason_fa = {
            'market_closed': 'بازار تعطیل است (آخر هفته)',
            'macro_blackout': 'پشت‌بند اخبار مهم — ورود ممنوع',
            'daily_loss_limit': 'سقف ضرر روزانه پر شده',
            'daily_trade_limit': 'سقف تعداد ترید روزانه پر شده',
            'position_limit': 'سقف پوزیشن باز پر شده',
        }
        _sr = str(proposal.get('skip_reason'))
        _base = _sr.split('_')[0] + ('_' + _sr.split('_')[1] if _sr.startswith('poor_rr') or _sr.startswith('sizing') else '')
        _label = _reason_fa.get(_sr) or _reason_fa.get(_base) or _sr
        brief += f"\n\n⚠️ اجرا نشد: {_label}"

    payload = {
        'ok': True, 'step': 'monitor', 'plan_id': plan.get('plan_id'),
        'monitor': monitor, 'proposal': proposal,
        'brief': brief,
        'will_execute_now': will_execute,
        'execution_result': execution_result,
        'account_policy': policy, 'performance_state': performance,
    }

    runtime['active_plan_id'] = plan.get('plan_id')
    runtime['last_step'] = 'monitor'
    runtime['last_monitor_action'] = monitor.get('action')
    save_runtime_state(_plan_dir(), runtime)
    return payload


def main():
    from bridge_client import BridgeClient
    bridge = BridgeClient()
    bridge.health()
    print(json.dumps(cycle(bridge), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
