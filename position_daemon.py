#!/usr/bin/env python3
"""Hermes Position Watchdog — second-by-second trade management.

While a position is open:
  - polls every 5s (vs 5-min cron)
  - runs trade management (breakeven / partial TP / early close)
  - tracks MFE/MAE (max favorable/adverse excursion)
When position closes:
  - sends a short lifecycle report to Telegram
When position opens:
  - sends instant "trade opened" notice
Runs as systemd user service 'hermes-position'.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv(BASE / '.env')

from bridge_client import BridgeClient
from engines import paths
from engines.bridge_payload import positions_list
from engines.trade_management import evaluate_trade_management, ladder_fields, build_tp_ladder
from engines.plan import setup_grade   # b111: ONE grade rule for all producers
from engines.auto_executor import evaluate_management_action
from engines.legacy_guards import (evaluate_news_lock, evaluate_time_exit,
                                   is_news_lock)

# b39: LOG_FILE removed — it was a dead import-time binding of
# paths.logs_dir() (log() below already resolves per call). Keeping it alive
# was a trap: any new caller would write to production logs under a test root.
DRY_RUN = os.getenv('HERMES_DRY_RUN', 'true').lower() not in {'0', 'false', 'no'}
POLL_SEC = 5


def _log_file() -> Path:
    """Resolved per call: tests redirect HERMES_DATA_ROOT after import, and a
    module-level constant would keep appending to the production log."""
    return paths.logs_dir() / 'position_daemon.log'


def log(msg: str):
    path = _log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    with path.open('a', encoding='utf-8') as f:
        f.write(f"[{ts}] {msg}\n")


def send_telegram(text: str):
    _tg(text, os.getenv('TELEGRAM_BOT_TOKEN', ''))


def send_ops(text: str):
    """b37: system-status alerts -> 3rd ops bot."""
    _tg(text, os.getenv('AUTOPILOT_REPORT_BOT_TOKEN', '') or os.getenv('TELEGRAM_BOT_TOKEN', ''),
        chat=os.getenv('AUTOPILOT_REPORT_CHAT_ID', '194015957'))


def _tg(text: str, token: str, chat: str | None = None):
    chat = chat or os.getenv('TELEGRAM_CHAT_ID', '194015957')
    if not token:
        return
    try:
        url = f'https://api.telegram.org/bot{token}/sendMessage'
        data = urllib.parse.urlencode({
            'chat_id': chat, 'text': text,
            'disable_web_page_preview': 'true',
        }).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception as e:
        log(f'telegram failed: {e}')


def load_state() -> dict:
    return paths.read_json_safe(paths.watchdog_state(),
                                {"positions": {}, "closed": []},
                                label="watchdog_state")


def save_state(state: dict):
    paths.write_json_atomic(paths.watchdog_state(), state, default=str)


def load_plan() -> dict:
    return paths.read_json_safe(paths.current_plan(), {}, label="current_plan")


def _pos_obj(raw: dict):
    class P:
        pass
    p = P()
    p.ticket = raw['ticket']; p.type = raw['type']; p.volume = raw['volume']
    # bridge sends 'price_open' (mt5_http_server_v2) — 'open_price' kept for legacy compat
    p.price_open = raw.get('price_open') or raw.get('open_price') or 0.0
    p.sl = raw.get('sl') or 0.0
    p.tp = raw.get('tp') or 0.0; p.profit = raw.get('profit', 0.0)
    # b32: broker open time (epoch, broker-server clock). Needed by
    # time_exit — without it the watchdog only ever knew when IT noticed
    # the position, so a daemon restart reset the 36h clock.
    p.time = raw.get('time')
    return p


def build_trade(raw: dict, plan: dict, wstate: dict) -> dict:
    """Shape a live position into the trade dict evaluate_trade_management expects.

    Quality fields come from the REAL plan quality (same derivation as
    hermes_runtime cycle) — hardcoded placeholders made partial/trail
    decisions constant regardless of market state.
    """
    p = _pos_obj(raw)
    execution = plan.get('execution') or {}
    quality = plan.get('quality') or {}
    # b111: alignment/trend_strength used to be read here to feed the inline
    # grade rule; the grade now comes from engines.plan.setup_grade, so the
    # two locals were dead.
    side = p.type if p.type in ('BUY', 'SELL') else ('BUY' if p.type == 0 else 'SELL')
    # b44 filter + b60 midpoint rebuild — b169: the inline block moved to
    # engines.trade_management.build_tp_ladder UNCHANGED, because
    # hermes_runtime's manage-fallback (the path that runs whenever this
    # watchdog is >60s stale) feeds the SAME evaluate_trade_management and
    # was shipping neither fix. Byte-identical behaviour here; see that
    # helper's docstring for #103326893 / #103976964.
    raw_levels = execution.get('tp_levels') or plan.get('targets') or []
    tp_levels = build_tp_ladder(p.price_open, side, p.tp, raw_levels)
    # b111 FIX 2026-09-07: the watchdog used to inline a PRE-b45 grade rule
    # here (no regime clause for an A, 'mixed' reaching B) while the entry
    # gate and hermes_runtime used the canonical one — so the ladder decision
    # that actually ran on a live position came from a looser rule than the
    # one that opened the trade. b109 filed that as a human-gate decision on
    # the premise that aligning it "would change the live breakeven lock".
    # Measured instead of assumed (scripts/b111_blast_radius_probe.py, ledger
    # data/backtest/b111_blast_radius.json): the premise was FALSE. Of 44
    # cells where the rules differ on grade, only 9 differ on a BROKER-VISIBLE
    # action, all one family (aligned + trend>=3.0 + a NON-continuation
    # regime), and engines.context._detect_regime cannot produce that
    # combination (0 of 320 swept vote x trend x geometry cells; 0 of the 65
    # real aligned+trend>=3 plans). The other 35 cells differ only in the
    # reason LABEL, and both labels carry close_fraction 1.0 →
    # bridge.close_position. Replaying the
    # 17 executed trades whose plan snapshot survives: 0 action differences.
    # The canonical rule is also never LOOSER than the old inline one, so
    # this cannot open a gate that was closed. One shared definition now lives
    # in engines.plan.setup_grade (the b109 lesson: three lookalikes drift).
    wd_grade = setup_grade(plan)
    return {
        'symbol': 'XAUUSD',
        'side': side,
        'entry_price': p.price_open,
        # b32: broker open time, consumed by _position_opened_at → time_exit.
        'time': getattr(p, 'time', None),
        'sl': p.sl or plan.get('invalidation') or p.price_open,
        'tp_levels': tp_levels,
        'tp_shares': execution.get('tp_shares') or [0.5, 0.3, 0.2],
        'scale_in_levels': [],
        'filled_tp_levels': wstate.get('filled_tp_levels', []),
        'breakeven_active': bool(wstate.get('breakeven_active', False)),
        'runner_active': bool(wstate.get('runner_active', True)),
        'scaled_in_levels': [],
        'volume': p.volume,
        'regime': quality.get('regime'),
        # b109: the ladder fields come from the ONE shared derivation
        # (engines.trade_management.ladder_fields), the same helper
        # hermes_runtime.cycle and the live-parity backtest use — so the three
        # producers can no longer drift apart field by field.
        #
        # THE GRADE IS NOW THE CANONICAL RULE (b111, 2026-09-07). It used to be
        # this file's own looser pre-b45 copy; see the note above build_trade's
        # return for the measurement that showed the divergence was inert.
        # engines.plan.setup_grade is the ONE definition shared with the entry
        # gate (auto_executor) and hermes_runtime, so the ladder can no longer
        # disagree with the decision that opened the trade.
        'setup_grade': wd_grade,
        **{k: v for k, v in ladder_fields(quality, wd_grade,
                                          session=plan.get('session')).items()
           if k != 'setup_grade'},
    }


# ── b32: legacy guards (news_lock / time_exit) in the watchdog ──
# hermes_runtime.cycle has had these since the legacy merge, but in
# production the runtime management block is SKIPPED whenever this
# watchdog is alive (heartbeat < 60s) — and the watchdog never called
# the guards at all. Result: news_lock and time_exit had no live
# executor anywhere. b31 made news_lock readable; b32 wires it here and
# b33 made the calendar PRODUCER actually deliver actionable events.
#
# The watchdog loop runs every 5s, so both inputs are throttled:
#   - calendar: rebuilt at most once per GUARD_CAL_TTL_SEC
#   - guard evaluation: at most once per GUARD_EVAL_TTL_SEC per ticket
# A news lock is a 30-minute window; a 60s decision latency is irrelevant,
# and re-modifying the SL every 5s would hammer the broker.
GUARD_CAL_TTL_SEC = 300
GUARD_EVAL_TTL_SEC = 60
# Broker-clock calibration: a sample is only plausible if the implied offset
# is within ±14h of UTC (every FX broker server timezone fits). Outside that
# the tick is stale (weekend gap, bridge stall) and must not be trusted —
# falling back to the watchdog's own detection time can only make time_exit
# fire EARLY, never late, which is the safe direction.
BROKER_OFFSET_SANITY_SEC = 14 * 3600
BROKER_OFFSET_WINDOW = 120          # ~10 min of 5s ticks
# Polls must arrive within this of each other for the tick stream to prove
# itself live; a longer gap means we cannot bound the tick's age.
BROKER_OFFSET_MAX_GAP_SEC = 60
_guard_cache = {"cal": None, "cal_at": 0.0, "last_eval": {}, "applied": {},
                "offsets": [], "prev_tick": (0.0, 0.0)}


def broker_utc_offset_sec(tick: dict, now: datetime) -> float:
    """Broker-server clock minus UTC, estimated from a LIVE tick stream.

    The bridge reports position open times as `int(p.time)` — epoch seconds
    in the BROKER'S server timezone, not UTC. hermes_runtime._epoch_to_iso
    has treated them as UTC since the legacy merge, which makes every
    position look ~3h YOUNGER than it is (measured 2026-08-30 against the
    two real fills in execution_log.csv: broker clock is UTC+3:05/+3:28).
    On the 36h time_exit that is a LATE exit; correcting it is the
    conservative direction.

    A single sample cannot separate offset from tick age:
    (tick.time - utc_now) = offset + age. So a sample is only accepted when
    the stream is provably live — tick time advancing in step with the wall
    clock between consecutive polls — which bounds `age` near zero. The
    estimate is then the MINIMUM accepted sample: residual error can only
    make a position look younger than it is (a late exit), never older, so
    this can never fire time_exit early. (NTP's minimum-delay argument.)

    Anything implausible — a weekend gap, a stalled bridge, a daemon
    restart onto an old tick — is rejected and the caller falls back to the
    watchdog's own detection time, which is later than the true open and so
    also errs toward an early-not-late exit.
    """
    data = tick.get('data', tick) if isinstance(tick, dict) else {}
    try:
        t = float(data.get('time') or 0)
    except (TypeError, ValueError):
        return _min_offset()
    if t <= 0:
        return _min_offset()
    wall = now.timestamp()
    diff = t - wall
    prev_t, prev_w = _guard_cache['prev_tick']
    live_stream = (prev_w > 0 and 0 < (wall - prev_w) <= BROKER_OFFSET_MAX_GAP_SEC
                   and (t - prev_t) >= 0.8 * (wall - prev_w))
    if live_stream and abs(diff) <= BROKER_OFFSET_SANITY_SEC:
        samples = _guard_cache['offsets']
        samples.append(diff)
        del samples[:-BROKER_OFFSET_WINDOW]
    _guard_cache['prev_tick'] = (t, wall)
    return _min_offset()


def _min_offset() -> float:
    """Best offset estimate so far, 0.0 (= trust nothing) when unmeasured."""
    samples = _guard_cache['offsets']
    return min(samples) if samples else 0.0


def publish_calibration(now: datetime | None = None) -> bool:
    """b35: share the watchdog's broker-clock calibration with the runtime.

    hermes_runtime's fallback time_exit (the ONLY manager when this watchdog
    is dead) cannot re-estimate the offset itself — a 15-min cycle has no
    consecutive polls to prove the tick stream is live, which is the
    precondition broker_utc_offset_sec demands. So it reads ours.

    Published only when at least one sample was actually accepted: 0.0 from
    _min_offset() means 'unmeasured', and writing that as a measurement would
    tell the runtime the broker clock IS UTC — the exact bug class b32 killed.
    """
    if not _guard_cache['offsets']:
        return False
    from engines import broker_clock
    return broker_clock.save_offset(_min_offset(), source='position_daemon',
                                    now=now)


def _guard_calendar(now: datetime) -> dict | None:
    """Calendar for the guards: plan context first, then a fresh fetch.

    hours_ahead=24 comfortably covers the 30-minute lock window; the bucket
    is rebuilt at most once per GUARD_CAL_TTL_SEC so the 5s loop does not
    hammer the calendar feed.
    """
    plan = load_plan()
    cal = ((plan.get('context') or {}).get('macro') or {}).get('calendar')
    if cal:
        return cal
    if now.timestamp() - _guard_cache['cal_at'] >= GUARD_CAL_TTL_SEC:
        _guard_cache['cal_at'] = now.timestamp()
        try:
            from engines.economic_calendar import get_upcoming_events
            _guard_cache['cal'] = get_upcoming_events(hours_ahead=24)
        except Exception as e:
            # fail-closed for the guard means "no lock this cycle", NOT a
            # trade block — news_lock only tightens stops, and the entry
            # paths have their own (b30 fail-closed) blackout gates.
            log(f'guard calendar failed: {e}')
            _guard_cache['cal'] = None
    return _guard_cache['cal']


def guard_fingerprint(guard: dict) -> tuple:
    """Identity of a guard action, for once-per-ticket application."""
    return (guard.get('action'), guard.get('new_sl'), guard.get('reason'))


def apply_legacy_guards(management: dict, trade: dict, wstate: dict,
                        market_price: float, ticket: int, now: datetime,
                        broker_offset: float = 0.0) -> dict:
    """Priority merge, mirroring hermes_runtime: news_lock(1) >
    time_exit(2) > core management(3+). Returns the winning action dict.

    A guard action is returned at most once per identical fingerprint:
    the caller records it in _guard_cache['applied'] ONLY after the broker
    accepts, so a rejected modify is retried on the next eval window while
    an accepted one never re-hammers the same SL change every 60s.
    """
    if now.timestamp() - _guard_cache['last_eval'].get(ticket, 0.0) < GUARD_EVAL_TTL_SEC:
        return management
    _guard_cache['last_eval'][ticket] = now.timestamp()
    try:
        cal = _guard_calendar(now)
        plan = load_plan()
        nl_trade = {**trade,
                    'entry_price': trade.get('entry_price') or market_price,
                    'sl': trade.get('sl') or 0,
                    'atr': plan.get('atr') or 5}
        guards = (evaluate_news_lock(nl_trade, market_price, cal, now),
                  evaluate_time_exit({'opened_at': _position_opened_at(
                      trade, wstate, now, broker_offset)}, now))
        for g in guards:
            if g and int(g.get('priority', 9)) < int(management.get('priority', 3)):
                if guard_fingerprint(g) in _guard_cache['applied'].get(str(ticket), []):
                    return management  # already applied & broker-accepted
                return g
    except Exception as e:
        log(f'guard eval error #{ticket}: {e}')
    return management


def _position_opened_at(trade: dict, wstate: dict, now: datetime,
                        broker_offset: float = 0.0) -> str | None:
    """When this position really opened, in UTC ISO.

    Prefers the broker's own open time (correct even if the watchdog was
    down or restarted mid-trade), de-rotated to UTC by `broker_offset`.
    Falls back to the watchdog's detection time — which is LATER than the
    true open, so it can only make a position look older, i.e. fire
    time_exit early rather than late. Never invent an age.
    """
    raw = trade.get('time') or trade.get('broker_time')
    try:
        v = float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        v = 0.0
    if v > 0:
        return datetime.fromtimestamp(v - broker_offset, tz=timezone.utc).isoformat()
    return wstate.get('opened_at')


def prune_guard_state(live_tickets: set) -> None:
    """Drop per-ticket guard memory for positions that no longer exist.

    Tickets are broker-unique so a leak is harmless for correctness, but the
    watchdog runs for weeks — without this the dicts grow forever.
    """
    keep = {int(t) for t in live_tickets}
    for key in ('last_eval', 'applied'):
        store = _guard_cache[key]
        for t in [t for t in store if str(t).lstrip('#') not in {str(k) for k in keep}
                  and t not in keep]:
            store.pop(t, None)


def manage_position(tkt: int, p: dict, plan: dict, tracked: dict, bridge,
                    price: float, now: datetime | None = None,
                    broker_offset: float = 0.0) -> None:
    """One watchdog management pass over a single live position (b32).

    Extracted from main() so the guard chain can be replayed against a fake
    bridge in tests — the live loop is not unit-testable, and an exit-path
    change that only runs in production is an untested exit policy.

    Mutates `tracked[str(tkt)]` (events / breakeven_active / filled TPs) and
    the guard cache; state is committed ONLY on broker acceptance (b7b/b10b).
    """
    now = now or datetime.now(timezone.utc)
    tkt_s = str(tkt)
    trade = build_trade(p, plan, tracked[tkt_s])
    mgmt = evaluate_trade_management(trade, price, now)
    mgmt_core = mgmt
    mgmt = apply_legacy_guards(mgmt, trade, tracked[tkt_s], price, int(tkt),
                              now, broker_offset)
    is_guard = mgmt is not mgmt_core
    if mgmt.get('action') in (None, 'hold'):
        return
    # DEFCON insights deliberately NOT passed — see the note
    # in hermes_runtime.cycle (runner-disabled maps to a
    # full market close; untested exit policy).
    res = evaluate_management_action(mgmt, bridge, int(tkt), dry_run=DRY_RUN)
    if res.get('executed'):
        tracked[tkt_s]['events'].append(f"مدیریت: {mgmt['action']} ({mgmt.get('reason','')})")
        log(f'MGMT #{tkt} {mgmt["action"]} -> ok')
        if is_guard:
            # b32: remember accepted guard actions so the
            # 60s re-eval never re-sends the same modify.
            fp = guard_fingerprint(mgmt)
            applied = _guard_cache['applied'].setdefault(str(tkt), [])
            if fp not in applied:
                _guard_cache['applied'][str(tkt)] = applied + [fp]
        if mgmt['action'] == 'move_stop_to_breakeven':
            # news_lock REUSES this action name to move SL to 0.5*ATR — it is
            # NOT the post-TP breakeven, and marking breakeven_active for it
            # would suppress the real BE move later. b32 wrote this inline;
            # b167 moved the predicate into legacy_guards so the runtime
            # fallback path shares it (the drift this bug class keeps causing).
            if not is_news_lock(mgmt):
                tracked[tkt_s]['breakeven_active'] = True
        elif mgmt['action'] == 'partial_take_profit':
            filled = list(tracked[tkt_s].get('filled_tp_levels', []))
            filled.append(mgmt.get('target_hit'))
            tracked[tkt_s]['filled_tp_levels'] = filled
    elif res.get('error'):
        log(f'MGMT #{tkt} {mgmt.get("action")} REJECTED -> {res["error"][:120]}')
        evs = tracked[tkt_s].setdefault('events', [])
        # one line per action per ticket — the 5s loop would
        # otherwise spam the lifecycle report with retries
        tag = f'reject:{mgmt.get("action")}'
        if tag not in tracked[tkt_s].setdefault('_rejected', []):
            tracked[tkt_s]['_rejected'] = tracked[tkt_s].get('_rejected', []) + [tag]
            evs.append(f"⚠️ مدیریت رد شد: {mgmt.get('action')} ({str(res['error'])[:60]})")
            # A rejected breakeven/trail move means the trade is still running
            # on its ORIGINAL stop — the retry loop keeps trying, but the
            # operator must know NOW, not at close report.
            send_telegram(f'⚠️ مدیریت رد شد #{tkt}: {mgmt.get("action")}\n'
                          f'{str(res["error"])[:120]}\n'
                          f'اتصال/SL اصلی هنوز فعال — تلاش مجدد خودکار')


def realized_pnl_usd(bridge, ticket: int):
    """b44: sum of broker-confirmed OUT deals for one position ticket.

    The close report used `last_profit` — the FLOATING pnl of the volume
    remaining at the final poll. After partial closes that number is not the
    trade result (#103326893: report said +1.83$, broker deals summed to
    -0.27$). Returns None when the bridge cannot answer (caller falls back).
    """
    try:
        res = bridge.get_history_deals(days=1) or {}
        deals = res.get('data') or []
        mine = [d for d in deals
                if int(d.get('position_id') or d.get('order') or 0) == int(ticket)]
        # require at least one OUT deal — otherwise history is not complete
        if not mine or not any(int(d.get('entry', 0)) != 0 for d in mine):
            return None
        # all deals incl. the IN one: its commission belongs to the trade too
        return round(sum(float(d.get('profit', 0)) + float(d.get('commission', 0))
                         + float(d.get('swap', 0)) for d in mine), 2)
    except Exception:
        return None


def close_reason(final_sl: float, final_tp: float, exit_price: float, side: str) -> str:
    if final_tp and ((side == 'SELL' and exit_price <= final_tp) or (side == 'BUY' and exit_price >= final_tp)):
        return "TP خورد"
    if final_sl and ((side == 'SELL' and exit_price >= final_sl) or (side == 'BUY' and exit_price <= final_sl)):
        return "SL خورد"
    return "خروج دستی/مدیریتی"


def main():
    log(f'Position watchdog started (dry_run={DRY_RUN})')
    bridge = BridgeClient()
    state = load_state()
    tracked = state.setdefault('positions', {})
    errors = 0

    while True:
        try:
            plan = load_plan()
            tick = bridge.get_tick('XAUUSD') or {}
            resp = bridge.get_positions('XAUUSD') or {}
            # ── Bridge-failure guard: a transient MT5 blip must NOT be read as
            # "all positions closed". Without this, live={} → every tracked
            # ticket gets a bogus CLOSED report at price 0, tracking is lost,
            # and on recovery the same ticket re-opens as a duplicate. ──
            price = float(tick.get('ask') or tick.get('bid') or 0)
            if price <= 0 or not resp.get('ok', 'data' in resp):
                errors += 1
                log(f'bridge unavailable (tick_ok={price > 0}, pos_ok={resp.get("error", "ok")}) — cycle skipped')
                if errors == 3:
                    send_ops('⚠️ واتچ‌داگ: بریج ۳ بار متوالی پاسخ نداد — مدیریت پوزیشن موقتاً متوقف')
                time.sleep(10 if errors < 10 else 30)
                continue
            bid = float(tick.get('bid') or price)
            ask = float(tick.get('ask') or price)
            # b32: broker-server clock minus UTC (see broker_utc_offset_sec)
            broker_offset = broker_utc_offset_sec(tick, datetime.now(timezone.utc))
            # b35: share the calibration with hermes_runtime's fallback
            # time_exit (throttled inside; only writes real measurements).
            publish_calibration()
            live = {int(p['ticket']): p for p in positions_list(resp)}
            # Normalize bridge field name: server sends 'price_open'; legacy code
            # below reads 'open_price'. Without this, every tracking iteration
            # raised KeyError and was swallowed by the outer handler.
            for p in live.values():
                if 'open_price' not in p and 'price_open' in p:
                    p['open_price'] = p['price_open']

            # ── Detect CLOSED positions → report ──
            for tkt in list(tracked.keys()):
                if int(tkt) not in live:
                    w = tracked.pop(tkt)
                    exit_price = price
                    side = w.get('side', '?')
                    entry = w.get('entry', 0)
                    dur_min = (datetime.now(timezone.utc) - datetime.fromisoformat(w['opened_at'])).total_seconds() / 60
                    mfe = w.get('mfe', 0.0); mae = w.get('mae', 0.0)
                    reason = close_reason(w.get('sl', 0), w.get('tp', 0), exit_price, side)
                    pnl_pts = (entry - exit_price) if side == 'SELL' else (exit_price - entry)
                    # b44: 'last_profit' is the FLOATING pnl of whatever volume
                    # remained at the end — after partial closes it is NOT the
                    # trade result (#103326893 reported +1.83$ while the real
                    # outcome was -0.27$ gross). Ask the broker for the sum of
                    # realized deals on this ticket; fall back to floating.
                    pnl_usd = realized_pnl_usd(bridge, int(tkt))
                    if pnl_usd is None:
                        pnl_usd = w.get('last_profit', 0.0)
                    events = w.get('events', [])
                    ev_txt = "\n".join(f"  • {e}" for e in events[-6:]) or "  (بدون رویداد)"
                    report = (
                        f"📕 گزارش معامله بسته‌شده (#{tkt})\n"
                        f"{side} {w.get('volume0', w.get('volume'))} لات @ {entry:.2f}\n"
                        f"خروج: {exit_price:.2f} — {reason}\n"
                        f"سود/ضرر: {pnl_usd:+.2f}$ ({pnl_pts:+.1f} پوینت)\n"
                        f"مدت: {dur_min:.0f} دقیقه\n"
                        f"بیشترین سود در مسیر: {mfe:+.1f} | بیشترین ضرر: {mae:+.1f}\n"
                        f"رویدادها:\n{ev_txt}"
                    )
                    send_telegram(report)
                    log(f'CLOSED #{tkt} pnl={pnl_usd:+.2f} reason={reason}')
                    state.setdefault('closed', []).append({
                        'ticket': tkt, 'at': datetime.now(timezone.utc).isoformat(),
                        'pnl': pnl_usd, 'reason': reason,
                    })
                    state['closed'] = state['closed'][-50:]

            # ── Track OPEN positions ──
            for tkt, p in live.items():
                tkt_s = str(tkt)
                side = p['type'] if p['type'] in ('BUY', 'SELL') else ('BUY' if p['type'] == 0 else 'SELL')
                cur_pts = (p['open_price'] - bid) if side == 'SELL' else (ask - p['open_price'])
                if tkt_s not in tracked:
                    tracked[tkt_s] = {
                        'side': side, 'volume': p['volume'], 'volume0': p['volume'],
                        'entry': p['open_price'],
                        'opened_at': datetime.now(timezone.utc).isoformat(),
                        'mfe': cur_pts, 'mae': cur_pts,
                        'sl': p.get('sl') or 0, 'tp': p.get('tp') or 0,
                        'last_profit': p.get('profit', 0),
                        'events': [f"باز شد @ {p['open_price']:.2f} (SL {p.get('sl')}, TP {p.get('tp')})"],
                    }
                    send_telegram(
                        f"📗 معامله باز شد (#{tkt})\n"
                        f"{side} {p['volume']} لات @ {p['open_price']:.2f}\n"
                        f"SL: {p.get('sl')} | TP: {p.get('tp')}\n"
                        f"نگهبان لحظه‌ای فعال است — گزارش پایان معامله می‌آید."
                    )
                    log(f'OPEN #{tkt} {side} {p["volume"]} @ {p["open_price"]}')
                else:
                    w = tracked[tkt_s]
                    w['mfe'] = max(w.get('mfe', cur_pts), cur_pts)
                    w['mae'] = min(w.get('mae', cur_pts), cur_pts)
                    w['last_profit'] = p.get('profit', 0)
                    # SL/TP change detection (breakeven etc.)
                    if (p.get('sl') or 0) != w.get('sl'):
                        w['events'].append(f"SL جابه‌جا شد: {w.get('sl')} → {p.get('sl')}")
                        w['sl'] = p.get('sl') or 0
                    if (p.get('tp') or 0) != w.get('tp'):
                        w['events'].append(f"TP جابه‌جا شد: {w.get('tp')} → {p.get('tp')}")
                        w['tp'] = p.get('tp') or 0
                    if p['volume'] != w.get('volume'):
                        w['events'].append(f"سیو بست: {w.get('volume')} → {p['volume']} لات")
                        w['volume'] = p['volume']

                # ── High-frequency management (every 5s) ──
                # b32: the whole chain (core management + news_lock/time_exit
                # guards + commit-on-broker-acceptance) lives in
                # manage_position() so it is unit-testable against a fake
                # bridge. The live loop used to inline it, which is why an
                # exit-path change could only ever be verified in production.
                if not DRY_RUN and plan:
                    manage_position(int(tkt), p, plan, tracked, bridge,
                                    bid if side == 'SELL' else ask,
                                    datetime.now(timezone.utc), broker_offset)

            # Guard memory must not grow forever on a daemon that runs weeks.
            prune_guard_state(set(live.keys()))
            save_state(state)
            (paths.plan_dir() / 'watchdog_heartbeat').write_text(
                datetime.now(timezone.utc).isoformat())
            errors = 0
            time.sleep(POLL_SEC)
        except KeyboardInterrupt:
            break
        except Exception:
            errors += 1
            err = traceback.format_exc().strip().splitlines()[-1]
            log(f'ERROR ({errors}): {err}')
            if errors == 10:
                send_ops(f'⚠️ Watchdog: ۱۰ خطای متوالی\n{err[:150]}')
            time.sleep(10 if errors < 5 else 30)


if __name__ == '__main__':
    main()
