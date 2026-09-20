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

from engines.context import build_plan_context, apply_bias_geometry
from engines.bridge_payload import positions_list, entry_open_count
from engines.smc import smc_analyse, merge_smc_with_classic
from engines.orchestrator import build_plan_from_context, route_runtime_step, evaluate_monitor_cycle, compute_xau_position_size
from engines.trade_management import (evaluate_trade_management, ladder_fields,
                                      build_tp_ladder)
from engines.risk import assess_account_policy, compute_performance_state
from engines.storage import load_current_plan, save_current_plan, load_runtime_state, save_runtime_state, load_performance_state, save_performance_state, append_execution_log, append_reassessment_log, append_risk_ledger
from engines.plan import setup_grade, apply_smc_merge, _entry_close, stale_at_birth
from engines.report import render_plan_brief, render_reassess_brief, render_monitor_brief, render_management_brief, render_execution_brief
from engines.macro_filter import apply_macro_guard
from engines.legacy_guards import (evaluate_time_exit, evaluate_news_lock,
                                   is_news_lock)
from engines.auto_executor import (
    evaluate_proposal, execute_trade, evaluate_management_action,
    MAX_OPEN_POSITIONS,
)
from engines.kill_switch import check_kill_switch

from engines import paths as _paths  # state paths resolved at CALL time (b39)

# b39: the old BASE_DIR/DATA_DIR/PLAN_DIR aliases are GONE. They bound
# _paths.get_data_root() at IMPORT time, so HERMES_DATA_ROOT (tests via
# hermetic, staging via env) could not move them — and the one consumer
# (scripts/probe_gates.py) now resolves through engines.paths directly.
# Live code must keep using _plan_dir() below.


def _plan_dir():
    """Resolve the plan dir at CALL time so tests can redirect the tree."""
    return _paths.plan_dir()

SYMBOL = 'XAUUSD'
TIMEFRAME = 'M5'
# Max ask-bid (in $) to allow a NEW entry. Normal XAUUSD spread here is ~0.18;
# news/rollover spikes can blow past 2.0. Backtests charge a flat 0.20 cost,
# so live must not enter when the real cost is multiples of that.
MAX_ENTRY_SPREAD = float(os.getenv('HERMES_MAX_SPREAD', '0.60'))


def _entry_spread_veto(tick) -> object | None:
    """monitor['spread_blocked'] value, or None if the quote is usable.

    Fail-closed: missing / unreadable / inverted quotes all veto. A wide
    spread returns the dollar width (existing observability). The old
    `except (TypeError, ValueError): pass` left the proposal unguarded —
    the b30 class on the plan path.
    """
    try:
        _tk = tick if isinstance(tick, dict) else {}
        _td = _tk.get('data', _tk)
        if not isinstance(_td, dict):
            _td = _tk if isinstance(_tk, dict) else {}
        _ask = float(_td.get('ask') or 0)
        _bid = float(_td.get('bid') or 0)
        if _ask <= 0 or _bid <= 0:
            return 'unreadable'
        _spr = _ask - _bid
        if _spr > MAX_ENTRY_SPREAD or _spr <= 0:
            return round(_spr, 2)
        return None
    except (TypeError, ValueError):
        return 'unreadable'


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


def _bar_time(row) -> int | None:
    """Open-epoch of an M5 bar, in either bridge shape (dict row or
    (time, high, low, close) tuple). None when unparseable."""
    try:
        if isinstance(row, dict):
            t = row.get('time', row.get('Time'))
            return int(t) if t is not None else None
        return int(row[0])
    except (TypeError, ValueError, IndexError, KeyError):
        return None


# b193: the predicate moved to engines.plan.stale_at_birth so the LAB funnel
# (backtest_real.strategy_signal) enforces it too — it used to live only here,
# which is exactly how b188(a) shipped to live but not to the lab. This alias
# keeps hermes_runtime._stale_at_birth importable (tests, scripts).
_stale_at_birth = stale_at_birth


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


def settled_confirm_rows(rows, now: datetime | None = None,
                         broker_offset: float | None = None) -> list[dict]:
    """b79 FIX — the M5 window for the monitor, immune to the broker clock.

    The bridge stamps every bar `time` on the BROKER SERVER clock (~UTC+3
    for CapitalXtend; measured 10798s via position_daemon calibration),
    while `now` is real UTC. The pre-b79 filter `_bt + 300 <= wall_now`
    therefore compared broker seconds against UTC seconds and rejected
    EVERY row: live m5_confirm_rows was permanently empty (proof:
    scripts/b79b_live_window_proof.py — 12 fetched, 0 kept, freshest bar
    "closes" 183 min in the future). Post-b193b that starves BOTH trigger
    lanes (pullback AND aggressive) -> no entry could fire live at all.

    Contract: the ONLY clock-safe settledness test is bar-relative — the
    bridge returns the forming bar LAST (b189), so a row strictly older
    than the freshest open has closed on any broker clock. The freshest
    row is kept only when a trustworthy broker calibration proves its
    close (open - offset + 300 <= now_utc); uncalibrated -> dropped.
    Degradations are conservative: at worst one extra closed bar is
    ignored for one cycle; a forming close can never enter (lookahead).
    """
    parsed = []
    for r in rows or []:
        bt = _bar_time(r)
        if bt is not None:
            parsed.append((bt, r))
    if not parsed:
        return []
    freshest = max(bt for bt, _ in parsed)
    now = now or datetime.now(timezone.utc)
    out = []
    for bt, r in parsed:
        if bt < freshest:
            out.append(r)                      # closed bar on ANY broker clock
        elif broker_offset is not None and (bt - broker_offset + 300) <= now.timestamp():
            out.append(r)                      # calibration proves it just closed
    return out


def _tick_obj(tick: dict):
    data = tick.get('data', tick) if isinstance(tick, dict) else {}
    ask = float(data.get('ask') or data.get('price') or 0)
    bid = float(data.get('bid') or ask or 0)
    return SimpleNamespace(ask=ask, bid=bid)


def _pos_type(p: dict) -> int:
    """Normalize position direction to MT5 int (0=BUY, 1=SELL).

    b34 CRITICAL FIX: bridge v2 (/api/positions) sends type as the STRING
    'BUY'/'SELL' (scripts/mt5_http_server_v2.py), but this did int(...) →
    ValueError → cycle() crashed → hermes_master crashed (no try/except in
    either) → EVERY 15-min tick died while a position was open and the
    watchdog was dead — i.e. exactly when the fallback manager is the only
    thing protecting the trade. position_daemon._pos_obj already handled
    both shapes; the two consumers must not disagree on the wire format.
    """
    t = p.get('type', 0)
    if isinstance(t, str):
        return 0 if t.strip().upper() == 'BUY' else 1
    try:
        return int(t or 0)
    except (TypeError, ValueError):
        return 1  # unknown non-buy → treat as SELL (never silently BUY)


def _pos_obj(p: dict):
    return SimpleNamespace(
        symbol=p.get('symbol', SYMBOL),
        ticket=int(p.get('ticket', p.get('position_ticket', 0)) or 0),
        type=_pos_type(p),
        volume=float(p.get('volume', 0) or 0),
        price_open=float(p.get('price_open', p.get('open_price', 0)) or 0),
        sl=float(p.get('sl', 0) or 0),
        tp=float(p.get('tp', 0) or 0),
        time=p.get('time'),  # broker epoch seconds (bridge ≥ v2.1) — feeds time_exit
    )


def _positions_list(resp: dict) -> list:
    # b66-follow-up: delegates to the ONE canonical reader (engines.
    # bridge_payload) — this private copy was the shape-safe original, but
    # being private is why four other consumers hand-rolled WORSE copies
    # (dashboards crashed on a 401 dict-'data' in the clean-worktree verify).
    # Name kept: hermes_runtime's own call sites + tests import it.
    return positions_list(resp)


def build_live_plan(bridge, now: datetime | None = None) -> tuple[dict | None, dict | None]:
    now = now or _now()
    session = _detect_session(now)
    m5 = _data_list(bridge.get_rates(SYMBOL, TIMEFRAME, 120))
    m15 = _data_list(bridge.get_rates(SYMBOL, 'M15', 80))  # analytical vote only (b28)
    h1 = _data_list(bridge.get_rates(SYMBOL, 'H1', 80))
    h4 = _data_list(bridge.get_rates(SYMBOL, 'H4', 80))
    # Right after a bridge/MT5 restart, M5 history may still be syncing — retry once
    if len(m5) < 50:
        import time as _t
        _t.sleep(4)
        m5 = _data_list(bridge.get_rates(SYMBOL, TIMEFRAME, 120))
    if not (m5 and h1 and h4):
        return None, {'ok': False, 'error': 'insufficient_market_data', 'counts': {'M5': len(m5), 'H1': len(h1), 'H4': len(h4)}, 'session': session}
    ctx = build_plan_context(m5, h1, h4, session, m15_rows=m15)
    smc_result = smc_analyse(m5, now=now, h1_rows=h1)
    merged = merge_smc_with_classic(ctx, smc_result)
    # b193: this 30-line block was build_live_plan's OWN copy of the merge; the
    # lab had a second copy that dropped the b188(a) veto. One definition now,
    # in engines.plan.apply_smc_merge, called by both paths. Behaviour here is
    # identical to the old inline code, including the display-only smc_* stamps
    # (passed via smc_result — the backtest omits them by passing nothing).
    apply_smc_merge(ctx, merged, entry_close=_entry_close(m5),
                    smc_result=smc_result, rebuild=apply_bias_geometry)
    plan = build_plan_from_context(ctx, now=now)
    return plan, None


def _infer_setup_grade(plan: dict) -> str:
    """b111: was a SECOND independent copy of the grade rule (auto_executor
    had one, position_daemon inlined a looser third). All three now read
    engines.plan.setup_grade; this alias keeps the name the runtime and the
    backtest funnel call. Behaviour is byte-identical to the old body."""
    return setup_grade(plan)


def _epoch_to_iso(ts, broker_offset: float = 0.0) -> str | None:
    """Bridge position time is broker epoch seconds; legacy_guards wants ISO.

    b35: `ts` is on the BROKER SERVER clock (~UTC+3), not UTC. Feeding it
    raw made every position look ~3h YOUNGER on the fallback path, so the
    36h time_exit fired ~3h LATE. Callers pass the watchdog's published
    calibration (engines/broker_clock); 0.0 = uncalibrated, same behaviour
    as before but only when there is genuinely no measurement to trust.
    """
    try:
        v = float(ts)
        if v > 0:
            return datetime.fromtimestamp(v - float(broker_offset or 0.0),
                                          tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    return None


def _fallback_opened_at(broker_time, wd_entry,
                        broker_offset: float | None) -> str | None:
    """Best available 'when did this position open, in UTC' for time_exit.

    Priority (b35), mirroring position_daemon._position_opened_at:
      1. broker epoch de-rotated by the watchdog's PUBLISHED calibration —
         accurate even when the watchdog was down mid-trade;
      2. the watchdog's own detection time (watchdog_state.json), which is
         within seconds of the true open while the daemon is healthy;
      3. raw broker epoch (UTC-misread → looks ~3h young) — the pre-b35
         behaviour, only when neither 1 nor 2 exists. Never invent an age.
    """
    if broker_offset is not None:
        iso = _epoch_to_iso(broker_time, broker_offset)
        if iso:
            return iso
    if isinstance(wd_entry, dict):
        detected = wd_entry.get('opened_at')
        if detected:
            return str(detected)
    return _epoch_to_iso(broker_time)


def _runtime_log(msg: str) -> None:
    """b37: the runtime had NO logger — every swallowed exception was
    invisible. Append to logs/runtime.log (resolved at CALL time so a test
    run with HERMES_DATA_ROOT can never write into production logs)."""
    try:
        path = _paths.logs_dir() / 'runtime.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        with path.open('a', encoding='utf-8') as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass  # logging must never take the trading cycle down


def _guard_brief_line(status: dict | None, ticket) -> str:
    """b37: make the guard outcome VISIBLE. An error or a blind calendar is
    appended to the brief (hermes_master sends it to Telegram on step=manage);
    a clean 'none' adds nothing so normal cycles stay quiet."""
    if not status:
        return ''
    state = status.get('state')
    if state in (None, 'none', 'applied'):
        return ''
    detail = str(status.get('detail') or '')[:160]
    tag = f" #ticket {ticket}" if ticket is not None else ''
    if state == 'error':
        return (f"\n\n🛑 گاردهای ایمنی (news_lock/time_exit) اجرا نشدند"
                f"{tag}: {detail} — مدیریت فقط بر زنجیره اصلی")
    if state == 'calendar_unavailable':
        return (f"\n\n⚠️ تقویم اخبار در دسترس نیست — news_lock این چرخه "
                f"نمی‌تواند قفل کند (time_exit فعال است)")
    return ''


def _plan_calendar(plan: dict) -> dict | None:
    """plan.context.macro.calendar — shape-safe.

    b37: the inline chain `plan.get('context',{}).get('macro',{}).get('calendar')`
    raised AttributeError whenever `context['macro']` was None — which the
    monitor path writes literally (`plan['context']['macro'] = macro_snap`,
    macro_snap=None after a failed analyze_macro). The exception landed in the
    guard merge's bare `except Exception: pass`, so BOTH safety guards were
    dropped in silence.
    """
    ctx = plan.get('context')
    macro = ctx.get('macro') if isinstance(ctx, dict) else None
    if not isinstance(macro, dict):
        return None
    cal = macro.get('calendar')
    return cal if isinstance(cal, (dict, list)) else None


def _guard_calendar(plan: dict, now: datetime) -> tuple[dict | None, str]:
    """Calendar for the management guards, with a live-fetch fallback.

    Returns (calendar, source) where source ∈ plan / plan_stale / fetched /
    unavailable. b37: news_lock is only as alive as the calendar it is handed,
    and a plan built by build_live_plan (plan/reassess step) carries NO macro
    context at all — the guard merge used to pass None and the lock could
    never fire. Mirrors position_daemon._guard_calendar: plan first, then a
    fresh fetch (the calendar module caches to disk, so this is cheap).
    """
    cal = _plan_calendar(plan)
    if isinstance(cal, dict) and cal.get('source') == 'unavailable':
        cal = None
    if cal:
        if isinstance(cal, list):      # raw event list — news_lock accepts it
            return cal, 'plan'
        return cal, ('plan' if not cal.get('stale') else 'plan_stale')
    try:
        from engines.economic_calendar import get_upcoming_events
        fetched = get_upcoming_events(hours_ahead=24) or {}
        # NOTE: get_upcoming_events returns 'high_impact'/'total_events', NOT
        # 'events' (that key belongs to fetch_economic_calendar). A real
        # 'no news today' bucket still carries total_events > 0; only a dead
        # feed is 'unavailable'/empty.
        dead = (fetched.get('source') == 'unavailable'
                or not (fetched.get('total_events') or fetched.get('high_impact')))
        if dead:
            return None, 'unavailable'
        return fetched, 'fetched'
    except Exception as e:
        _runtime_log(f'guard calendar failed: {type(e).__name__}: {e}')
        return None, 'unavailable'


def evaluate_legacy_guards(management: dict, plan: dict, trade: dict,
                           p, market_price: float, now: datetime,
                           broker_offset: float | None,
                           wd_entry: dict | None = None) -> tuple[dict, dict]:
    """b37 — priority merge with an OBSERVABLE outcome.

    news_lock(1) > time_exit(2) > core management(3+), mirroring
    position_daemon.apply_legacy_guards. The old inline block in cycle()
    ended in `except Exception: pass`: any broken plan shape or calendar
    error silently DROPPED both guards — the same fail-open hole class b30
    closed on the entry side, and worse than the daemon's version because
    the runtime did not even log it.

    Now returns (management, guards_status):
      status['state'] = 'applied' | 'none' | 'error'
      status['detail'] = reason / error text (surfaced in the brief + payload
                         so hermes_master can alert)
    A guard-eval error deliberately does NOT block new entries: the entry
    path has its own fail-closed blackout gate (b30), and with
    MAX_OPEN_POSITIONS=1 a cycle that just failed to manage an open position
    cannot open a second one anyway. It IS loud — log + brief + Telegram.
    """
    status: dict = {'state': 'none', 'guards': 'news_lock,time_exit'}
    try:
        cal, cal_src = _guard_calendar(plan, now)
        status['calendar'] = cal_src
        if cal_src == 'unavailable':
            # news_lock cannot evaluate without a calendar. Not an error, but
            # the operator must know the lock was blind this cycle.
            status['state'] = 'calendar_unavailable'
        opened_at = _fallback_opened_at(getattr(p, 'time', None),
                                        wd_entry, broker_offset)
        nl_trade = {**trade,
                    'entry_price': getattr(p, 'price_open', market_price),
                    'sl': getattr(p, 'sl', 0),
                    'atr': plan.get('atr') or (plan.get('quality') or {}).get('atr') or 5}
        guards = (evaluate_news_lock(nl_trade, market_price, cal, now),
                  evaluate_time_exit({'opened_at': opened_at}, now))
        for g in guards:
            if g and int(g.get('priority', 9)) < int(management.get('priority', 3)):
                status['state'] = 'applied'
                status['detail'] = g.get('reason')
                return g, status
        return management, status
    except Exception as e:
        status['state'] = 'error'
        status['detail'] = f'{type(e).__name__}: {e}'
        _runtime_log(f"guard eval error #{getattr(p, 'ticket', '?')}: "
                     f"{status['detail']} — falling back to core management")
        return management, status


def _load_closed_trades(bridge, days=7) -> tuple[list[dict], bool]:
    """Closed deals for the daily-loss / DEFCON / kill-switch window.

    Returns (deals, readable). `readable=False` means the book is unknown —
    callers must NOT treat [] as "no losses today" (that is the b45 class
    on the PnL gates: a 401 history reply used to look like a clean day).
    `ok` missing with a real list is still readable (same leniency as
    positions_list). `ok: false` / non-list / exception = unreadable.
    """
    try:
        r = bridge.get_history_deals(SYMBOL, days)
    except Exception:
        return [], False
    if not isinstance(r, dict) or r.get('ok') is False:
        return [], False
    data = r.get('data', r.get('deals', []))
    if not isinstance(data, list):
        return [], False
    return [d for d in data if isinstance(d, dict)], True


def _performance_and_policy(bridge, account_resp: dict, now: datetime) -> dict:
    account = _account_obj(account_resp)
    # b45 FIX 2026-08-31: the bridge /api/account payload has NO `positions`
    # field, so account.positions was ALWAYS 0 — the MAX_OPEN_POSITIONS=1 gate
    # never fired and a second position was opened on top of the first
    # (14:15 + 14:30 UTC sells, net -56.7$). Count real positions from the
    # positions endpoint; fall back to the account field only if it exists.
    try:
        _pr = bridge.get_positions(SYMBOL)
        # b45 follow-up: positions_list() of a 401/MT5 error is [] — that
        # used to read as "nothing open" and let a second ticket stack.
        # entry_open_count fail-closes the ENTRY gate only (daemon still
        # uses positions_list so it does not mark every ticket CLOSED).
        _open_ct = entry_open_count(_pr, slot_full=MAX_OPEN_POSITIONS)
    except Exception:
        _open_ct = MAX_OPEN_POSITIONS
    account.positions = max(int(account.positions or 0), _open_ct)
    today = now.date().isoformat()
    closed, history_ok = _load_closed_trades(bridge, 7)
    if history_ok:
        perf = compute_performance_state(
            load_performance_state(_plan_dir()), today, account.balance, closed)
        save_performance_state(_plan_dir(), perf)
    else:
        # Keep last persisted numbers — do not recompute from an empty
        # window that would look like a clean book (kill switch / daily
        # cap / DEFCON going blind). evaluate_proposal refuses the entry.
        perf = load_performance_state(_plan_dir()) or {}
    policy = assess_account_policy(account.balance, account.equity, account.margin_free, account.margin, float(perf.get('daily_pnl', 0) or 0), int(perf.get('loss_streak', 0) or 0), account.positions)
    policy['history_ok'] = history_ok
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
        # b53: the executor sizes risk per ENTRY STYLE. Without the tag the
        # weakest lane (no-trigger discount) traded at full 2% like the
        # strongest — M5 parity backtest: discount WR 52% vs premium 65%.
        'execution_style': monitor.get('execution_style'),
        'price': tick_price,
        'at': datetime.now(timezone.utc).isoformat(),
    }


def _skip_reason_detail(proposal: dict, brief: str) -> str:
    """b185: render the plural rejection list as ONE supplementary line.

    The b172 census measured proposal['skip_reasons'] WRITE-ONLY: written at
    677 (macro veto) and 782 (entry vetoes) from evaluate_proposal's `reasons`,
    read by nothing — when the singular headline was a translated label
    ('daily_loss_limit') or a monitor veto line, the LIST carried facts the
    brief dropped (the actual loss pct, the failing grade, a fail-closed gate
    error's text). This is that missing reader. Observability only: it can add
    one string to the brief, never remove a block or touch a verdict.

    Dedupe rules (keep single-gate cycles byte-identical): an entry that is
    already a substring of the rendered brief (e.g. poor_rr_1.20 printed as
    the headline, a macro reason already shown by the monitor veto line) or
    contained in the singular skip_reason itself is dropped.
    """
    rs = proposal.get('skip_reasons')
    if not isinstance(rs, (list, tuple)):
        return ''
    _sr = str(proposal.get('skip_reason') or '').lower()
    hay = str(brief or '').lower()
    parts = []
    for item in rs:
        if item is None:
            continue
        s = ' '.join(str(item).split())
        if not s:
            continue
        low = s.lower()
        if (_sr and low in _sr) or low in hay:
            continue
        parts.append(s[:60])
        if len(parts) >= 4:
            break
    if not parts:
        return ''
    return "دلایل تکمیلی: " + " · ".join(parts[:4])


def _watchdog_alive(now: datetime) -> bool:
    """Is the 5s position watchdog reporting fresh? (b207: hoisted out of
    cycle so the HALTED branch and the normal path share ONE heartbeat
    reader — pure read, no side effect, same 60s bound, same fail-closed
    'unknown heartbeat == dead' behaviour as before.)"""
    hb = _plan_dir() / 'watchdog_heartbeat'
    if not hb.exists():
        return False
    try:
        age = (now - datetime.fromisoformat(hb.read_text().strip())).total_seconds()
        return age < 60
    except Exception:
        return False


def _manage_positions_fallback(bridge, plan, positions, runtime, tick,
                               now, dry_run, policy, performance) -> dict:
    """b207 — the runtime's FALLBACK management pass, extracted VERBATIM.

    Returns {'payload': dict|None, 'guard_status': dict|None}. A non-None
    payload means a protective action was taken (and possibly executed): the
    caller returns it directly — the SAME early-return-on-first-action
    semantics cycle() has had since b34/b37/b167/b169 (extract, do not
    rewrite; b109/b111: a fix to this ladder must not need to be applied
    twice). guard_status is the last position's legacy-guard outcome, for
    the caller's brief visibility (b37).

    b207: this body is ALSO reachable while the kill switch is HALTED
    (heartbeat stale + open position + a plan) — the halt may block NEW
    ENTRIES but must never cancel the last line of protective defence on
    exposure already on the book.
    """
    guard_status_last: dict | None = None
    tick_obj = _tick_obj(tick if isinstance(tick, dict) else {})
    runtime_state = runtime
    # b35: the bridge stamps position times on the BROKER SERVER clock
    # (~UTC+3). The watchdog measures that offset from its live 5s tick
    # stream and publishes it (engines/broker_clock); a 15-min cycle
    # cannot re-measure it, so we read theirs. None = no trustworthy
    # calibration → fall back to the watchdog's own detection time.
    try:
        from engines.broker_clock import load_offset
        broker_offset = load_offset(now=now)
    except Exception:
        broker_offset = None
    wd_positions = _paths.read_json_safe(
        _paths.watchdog_state(), {}, label='watchdog_state') or {}
    if not isinstance(wd_positions, dict):
        wd_positions = {}
    wd_positions = wd_positions.get('positions') or {}
    for raw in positions:
        p = _pos_obj(raw)
        _side = 'BUY' if p.type == 0 else 'SELL'
        trade = {
            'symbol': p.symbol, 'side': _side, 'entry_price': p.price_open,
            'sl': p.sl or plan.get('invalidation') or p.price_open,
            # b169: THE SAME ladder the watchdog builds (b44 wrong-side
            # filter + b60 midpoint rebuild), extracted to
            # engines.trade_management.build_tp_ladder. This fallback path
            # used to feed evaluate_trade_management the RAW plan targets:
            # a stale TP1 on the wrong side of entry made
            # _next_unfilled_target return a blocked level (the b44
            # profit_side guard then dead-locks every farther target), so
            # the manage loop could neither take profit, arm breakeven nor
            # trail — it could only time-exit. That is exactly the
            # b167/b168 lesson: a fix to this ladder must be censused on
            # EVERY producer of the trade dict, not just the daemon.
            'tp_levels': build_tp_ladder(
                p.price_open, _side, p.tp,
                (plan.get('execution') or {}).get('tp_levels') or plan.get('targets') or []),
            'tp_shares': (plan.get('execution') or {}).get('tp_shares') or [0.5, 0.3, 0.2],
            'scale_in_levels': (plan.get('execution') or {}).get('scale_in_levels') or [],
            'filled_tp_levels': ((runtime_state.get('management') or {}).get(str(p.ticket), {}) or {}).get('filled_tp_levels', []),
            'breakeven_active': bool(((runtime_state.get('management') or {}).get(str(p.ticket), {}) or {}).get('breakeven_active', False)),
            'runner_active': bool(((runtime_state.get('management') or {}).get(str(p.ticket), {}) or {}).get('runner_active', True)),
            'scaled_in_levels': ((runtime_state.get('management') or {}).get(str(p.ticket), {}) or {}).get('scaled_in_levels', []),
            'volume': p.volume, 'regime': (plan.get('quality') or {}).get('regime'),
            # b109: the ladder fields come from the ONE shared derivation
            # (engines.trade_management.ladder_fields), same helper the
            # watchdog and the live-parity backtest use. The values are
            # byte-identical to the inline block this replaces.
            **ladder_fields(plan.get('quality') or {},
                            _infer_setup_grade(plan),
                            session=plan.get('session')),
        }
        market_price = float(tick_obj.ask if trade['side'] == 'BUY' else tick_obj.bid)
        management = evaluate_trade_management(trade, market_price, now)

        # ── Legacy priority merge: news_lock(1) > time_exit(2) > legacy chain(3+) ──
        # b37: was an inline `try: ... except Exception: pass` — a broken
        # plan shape (context['macro']=None is written by the monitor path
        # itself) or a calendar error dropped BOTH guards with no log and
        # no trace in the report. Now a named helper that logs, tags the
        # status, and hands it to the brief/payload.
        management, guard_status = evaluate_legacy_guards(
            management, plan, trade, p, market_price, now, broker_offset,
            wd_entry=wd_positions.get(str(p.ticket)))
        guard_status_last = guard_status

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
                # b167: a news lock REUSES this action name (b32's lesson,
                # until now enforced only in the watchdog). Claiming the
                # flag for it would suppress the REAL post-TP1 breakeven.
                if not is_news_lock(management):
                    management['breakeven_active'] = True
            elif management.get('action') in {'close_runner', 'close_trade_early'}:
                management['runner_active'] = False

            brief = render_management_brief(plan, management)
            brief += _guard_brief_line(guard_status, p.ticket)
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
                    # b167: gate the PERSISTED flag too — this is the write
                    # that survives into the next cycle; the in-memory dict
                    # above is discarded on return.
                    if not is_news_lock(management):
                        tstate['breakeven_active'] = True
                elif management.get('action') in {'close_runner', 'close_trade_early'}:
                    tstate['runner_active'] = False
            save_runtime_state(_plan_dir(), runtime)
            return {'payload': {'ok': True, 'step': 'manage', 'plan_id': plan.get('plan_id'), 'management': management, 'guards': guard_status, 'brief': brief, 'will_execute_now': mgmt_result.get('executed', False), 'account_policy': policy, 'performance_state': performance}, 'guard_status': guard_status}
    return {'payload': None, 'guard_status': guard_status_last}


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
    # b207: ONE heartbeat read per cycle, shared by the halted branch and the
    # normal fallback gate below (pure read, no side effect).
    watchdog_alive = _watchdog_alive(now)

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
        halted_payload = {
            'ok': True, 'step': 'halted', 'kill_switch': kill,
            'brief': brief, 'will_execute_now': False,
            'account_policy': policy, 'performance_state': performance,
        }
        # b207: the halt must block NEW ENTRIES (everything below this point —
        # plan build, monitor, proposal, execution — stays unreachable) but it
        # must NOT cancel the only protective manager that is left when the
        # watchdog is ALSO down: news_lock, time_exit, TP1 partial, breakeven
        # and the runner trail would otherwise freeze for the whole 4h
        # cooldown on an open, losing position (the drawdown leg can only fire
        # with a position on the book). Tightening-only: this pass can modify
        # SL / partial-TP / close, never open. Handoff rule intact: it runs
        # only when the watchdog heartbeat is stale, exactly like the normal
        # path — no double-manager race.
        if positions and old_plan and not watchdog_alive:
            guard = _manage_positions_fallback(
                bridge, old_plan, positions, runtime, tick, now, dry_run,
                policy, performance)
            if guard['payload'] is not None:
                mp = guard['payload']
                mp['kill_switch'] = kill
                mp['halted'] = True
                mp['brief'] += (f"\n\n🛑 توقف سوییچ فعال است ({kill.get('reason')}) — "
                                "فقط اقدام حفاظتی بالا روی پوزیشن باز اجرا شد؛ "
                                "ورود جدید مسدود است")
                _runtime_log(f"b207: protective action "
                             f"{(mp.get('management') or {}).get('action')} ran "
                             f"UNDER kill-switch halt (watchdog stale)")
                return mp
            # No action due — but guard health must still reach the operator
            # on the halted brief (b37 visibility on the halted path).
            _gline = _guard_brief_line(guard['guard_status'], None)
            if _gline:
                halted_payload['brief'] += _gline
                halted_payload['guards'] = guard['guard_status']
        return halted_payload

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
            plan_brief = render_reassess_brief(old_plan, plan)
        else:
            plan_brief = render_plan_brief(plan)
        # b41 CRITICAL: do NOT return here. next_reassessment is now +5min
        # (M5 scalping) while the cron ticks every 15min, so EVERY tick routed
        # to 'reassess' — and this early return meant evaluate_monitor_cycle
        # and the entry path NEVER ran. Measured: zero entries since 2026-08-30
        # even while price crossed the sell zone and the breakout trigger.
        # The fresh plan now flows straight into position management + entry
        # evaluation in the SAME cycle.
    else:
        plan_brief = None
        plan = old_plan

    if not plan:
        return {'ok': False, 'step': 'plan_missing', 'error': 'no_current_plan', 'will_execute_now': False}

    # ── Manage Existing Positions ──
    # Skip if position watchdog daemon is alive (manages every 5s)
    guard_status_last: dict | None = None
    if positions and not watchdog_alive:
        guard = _manage_positions_fallback(bridge, plan, positions, runtime,
                                           tick, now, dry_run, policy,
                                           performance)
        guard_status_last = guard['guard_status']
        if guard['payload'] is not None:
            return guard['payload']

    # ── Monitor for New Entry ──
    # b37: if the fallback loop ran but took no action, a guard error or a
    # blind calendar must still reach the operator — otherwise the cycle
    # reports a clean 'monitor' step while both safety guards were skipped.
    # (A new entry is already impossible here: MAX_OPEN_POSITIONS=1 and
    # evaluate_proposal's position_limit blocks it — the guard failure is a
    # VISIBILITY problem, not a gate-bypass one.)
    guard_note = _guard_brief_line(guard_status_last, None) if positions else ''
    # b187: the entry trigger needs real M5 confirmation, not just "price is in
    # the zone". b79: the window must be built clock-safe — bar stamps are on
    # the BROKER clock (~UTC+3) while `now` is real UTC, so the old wall-clock
    # filter kept NOTHING and every entry lane was dead since b193b shipped.
    # settled_confirm_rows uses bar-relative settledness (forming bar = the
    # freshest open) plus the daemon's published broker calibration for the
    # freshest row only. Fail-closed intact: empty/absent rows => no trigger.
    try:
        from engines.broker_clock import load_offset
        _broker_off = load_offset(now=now)
    except Exception:
        _broker_off = None
    m5_confirm_rows = settled_confirm_rows(
        _data_list(bridge.get_rates(SYMBOL, TIMEFRAME, 12)), now=now,
        broker_offset=_broker_off)
    monitor = evaluate_monitor_cycle(plan, price=price, now=now, m5_rows=m5_confirm_rows)
    # Stale plan (price ran far from zones) → force reassess next cycle
    if 'plan_stale' in str(monitor.get('reason', '')):
        plan['next_reassessment'] = now.isoformat()
        save_current_plan(_plan_dir(), plan)
    proposal = _build_proposal(plan, monitor, policy, price)

    # ── Spread gate: news/rollover spikes blow XAUUSD past 2.0$ (normal 0.18).
    # Cost is linear in trades; entering into a wide spread hands the edge to
    # the broker. Read-only tick check — blocks the PROPOSAL, never management.
    if proposal is not None:
        _blk = _entry_spread_veto(tick)
        if _blk is not None:
            proposal = None
            monitor['spread_blocked'] = _blk

    if proposal is not None:
        # News blackout on the entry path. hermes_master never passed
        # macro_calendar, so this guard was dead in production — fetch the
        # cached calendar here so EVERY caller is protected (the calendar
        # module caches to disk; this is cheap).
        # b30 FAIL CLOSED: `except Exception: pass` left the proposal
        # UNguarded whenever the calendar module itself broke — no news
        # visibility used to mean 'no blackout'. Now a gate error blocks the
        # entry, same as a real blackout.
        try:
            from engines.economic_calendar import fetch_economic_calendar
            from engines.macro_filter import evaluate_macro_filter
            cal = (macro_calendar or {}).get('calendar') or fetch_economic_calendar()
            filt = (macro_calendar or {}).get('filter_result') or evaluate_macro_filter(cal, now)
            proposal = apply_macro_guard(proposal, filt)
            if filt.get('reason') == 'calendar_unavailable':
                monitor['calendar_unavailable'] = True
        except Exception as e:
            proposal = apply_macro_guard(
                proposal, {'allowed': False, 'reason': 'macro_gate_error',
                           'error': str(e)[:200]})

        # b170 OBSERVABILITY: a macro-blocked proposal is filtered out by the
        # `not proposal.get('blocked')` gate below, so it NEVER reached
        # evaluate_proposal and therefore never got a skip_reason — the brief
        # could not distinguish 'news blackout killed a real setup' from 'no
        # setup at all'. Exactly the window the operator asks why nothing
        # traded. Reporting only: no gate, no sizing, no verdict changes.
        if proposal is not None and proposal.get('blocked'):
            _mr = str(proposal.get('reason') or 'macro_block')
            proposal['skip_reason'] = 'macro_blackout'
            proposal['skip_reasons'] = [_mr]
            monitor['macro_blocked'] = _mr

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
                # b139: per-trade risk-stack audit (execution_style + the other
                # three dampers), written to its own sidecar ledger — see
                # engines/storage.append_risk_ledger for why not inline.
                # Observability only: a ledger failure must never touch a trade.
                try:
                    append_risk_ledger(_plan_dir(), dict(
                        eval_result.get('risk_stack') or {},
                        at=now.isoformat(), lane='plan',
                        plan_id=plan.get('plan_id'), side=cmd.get('side'),
                        lot=cmd.get('lot'), entry=cmd.get('entry'),
                        sl=cmd.get('sl'), tp=cmd.get('tp'),
                        grade=eval_result.get('grade'),
                        risk_usd=eval_result.get('risk_usd'),
                        # b144: the join key. Same value execution_log records,
                        # so the sidecar row reaches realized P&L on its own
                        # ticket instead of by timestamp guess.
                        ticket=(execution_result.get('result') or {}).get(
                            'ticket')))
                except Exception:
                    pass
        else:
            proposal['skip_reason'] = eval_result.get('reason')
            proposal['skip_reasons'] = eval_result.get('reasons', [])

    # Build brief
    brief = render_monitor_brief(plan, monitor)
    if guard_note:
        brief += guard_note
    if will_execute and execution_result:
        brief += "\n\n" + render_execution_brief(plan, execution_result)
    elif proposal and proposal.get('skip_reason'):
        _reason_fa = {
            'market_closed': 'بازار تعطیل است (آخر هفته)',
            'macro_blackout': 'پشت‌بند اخبار مهم — ورود ممنوع',
            'daily_loss_limit': 'سقف ضرر روزانه پر شده',
            'daily_trade_limit': 'سقف تعداد ترید روزانه پر شده',
            'position_limit': 'سقف پوزیشن باز پر شده',
            'stop_too_tight': 'استاپ داخل نویز طلا — ورود ممنوع',
            'history_unavailable': 'تاریخچه معاملات خوانده نشد — ورود ممنوع',
        }
        _sr = str(proposal.get('skip_reason'))
        _base = _sr.split('_')[0] + ('_' + _sr.split('_')[1] if _sr.startswith('poor_rr') or _sr.startswith('sizing') else '')
        _label = _reason_fa.get(_sr) or _reason_fa.get(_base) or _sr
        brief += f"\n\n⚠️ اجرا نشد: {_label}"
        # b185 OBSERVABILITY: the plural rejection list (written at 677/782
        # from evaluate_proposal's `reasons`) was measured WRITE-ONLY by the
        # b172 census — zero production readers. It carries gate CONTEXT the
        # singular headline drops: on `daily_loss_limit` the list holds the
        # actual loss pct, on `setup_grade_C` the failing grade, on
        # defcon/cooldown/learning blocks the level or the gate error. This
        # is the reader. Observability only: appends one detail string,
        # never removes a block, never touches a gate/verdict/sizing path.
        # Deduped against the brief-so-far so paths where the headline IS
        # the raw reason (poor_rr, market_closed) or the monitor veto line
        # already printed it (macro_blackout) stay byte-identical.
        _detail = _skip_reason_detail(proposal, brief)
        if _detail:
            brief += "\n" + _detail

    payload = {
        'ok': True, 'step': 'monitor', 'plan_id': plan.get('plan_id'),
        'monitor': monitor, 'proposal': proposal,
        'brief': brief,
        'will_execute_now': will_execute,
        'execution_result': execution_result,
        'account_policy': policy, 'performance_state': performance,
    }
    # b41: carry the fresh plan/reassess brief + bias flip so hermes_master
    # still reports them (previously the reassess early-return was the only
    # place these were produced).
    if step in {'plan', 'reassess'}:
        payload['plan'] = plan
        payload['plan_brief'] = plan_brief
        payload['previous_bias'] = (old_plan or {}).get('bias')
        payload['new_bias'] = plan.get('bias')
    if guard_status_last:
        payload['guards'] = guard_status_last

    runtime['active_plan_id'] = plan.get('plan_id')
    runtime['last_step'] = 'monitor'
    runtime['last_monitor_action'] = monitor.get('action')
    save_runtime_state(_plan_dir(), runtime)
    return payload


def main():
    # b65 (found by the b64 audit): this entrypoint read NO env — no
    # load_dotenv (so the bridge token was missing → 401) and cycle() was
    # called with its default dry_run=False, i.e. a bare
    # `python3 hermes_runtime.py` was a LIVE-order path. hermes_master is
    # the production entry and always passes dry_run=DRY_RUN; this manual
    # one now honours the same documented knob (default: dry-run).
    try:
        from dotenv import load_dotenv
    except ImportError:
        from env_loader import load_dotenv  # python-dotenv missing → local fallback
    load_dotenv(Path(__file__).resolve().parent / '.env')
    dry_run = os.getenv('HERMES_DRY_RUN', 'true').lower() not in {'0', 'false', 'no'}
    from bridge_client import BridgeClient
    bridge = BridgeClient()
    bridge.health()
    print(json.dumps(cycle(bridge, dry_run=dry_run), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
