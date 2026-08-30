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
from engines.trade_management import evaluate_trade_management
from engines.auto_executor import evaluate_management_action

LOG_FILE = paths.logs_dir() / 'position_daemon.log'
DRY_RUN = os.getenv('HERMES_DRY_RUN', 'true').lower() not in {'0', 'false', 'no'}
POLL_SEC = 5


def log(msg: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    with LOG_FILE.open('a', encoding='utf-8') as f:
        f.write(f"[{ts}] {msg}\n")


def send_telegram(text: str):
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat = os.getenv('TELEGRAM_CHAT_ID', '194015957')
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
    trend = float(quality.get('trend_strength', 0) or 0)
    alignment = quality.get('alignment', '')
    return {
        'symbol': 'XAUUSD',
        'side': p.type if p.type in ('BUY', 'SELL') else ('BUY' if p.type == 0 else 'SELL'),
        'entry_price': p.price_open,
        'sl': p.sl or plan.get('invalidation') or p.price_open,
        'tp_levels': execution.get('tp_levels') or plan.get('targets') or [],
        'tp_shares': execution.get('tp_shares') or [0.5, 0.3, 0.2],
        'scale_in_levels': [],
        'filled_tp_levels': wstate.get('filled_tp_levels', []),
        'breakeven_active': bool(wstate.get('breakeven_active', False)),
        'runner_active': bool(wstate.get('runner_active', True)),
        'scaled_in_levels': [],
        'volume': p.volume,
        'regime': quality.get('regime'),
        'setup_grade': ('A' if alignment == 'aligned' and trend >= 3.0
                        else 'B' if alignment in ('aligned', 'mixed') and trend >= 1.2 else 'C'),
        'momentum_strength': min(1.0, max(0.2, trend / 2.0)),  # ATR units → 0-1
        'volatility_state': 'high' if trend >= 3.0 else 'normal',
        'structure_state': 'healthy' if alignment == 'aligned' else 'mixed',
        'session_phase': plan.get('session'),
        'rr_remaining': 2.0,
        'thesis_valid': alignment != 'counter',
        'exposure_fraction': 0.5,
    }


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
                    send_telegram('⚠️ واتچ‌داگ: بریج ۳ بار متوالی پاسخ نداد — مدیریت پوزیشن موقتاً متوقف')
                time.sleep(10 if errors < 10 else 30)
                continue
            bid = float(tick.get('bid') or price)
            ask = float(tick.get('ask') or price)
            live = {int(p['ticket']): p for p in resp.get('data', [])}
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
                    pnl_usd = w.get('last_profit', 0.0)
                    events = w.get('events', [])
                    ev_txt = "\n".join(f"  • {e}" for e in events[-6:]) or "  (بدون رویداد)"
                    report = (
                        f"📕 گزارش معامله بسته‌شده (#{tkt})\n"
                        f"{side} {w.get('volume')} لات @ {entry:.2f}\n"
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
                        'side': side, 'volume': p['volume'], 'entry': p['open_price'],
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
                if not DRY_RUN and plan:
                    trade = build_trade(p, plan, tracked[tkt_s])
                    mgmt = evaluate_trade_management(trade, bid if side == 'SELL' else ask,
                                                     datetime.now(timezone.utc))
                    if mgmt.get('action') not in (None, 'hold'):
                        # DEFCON insights deliberately NOT passed — see the note
                        # in hermes_runtime.cycle (runner-disabled maps to a
                        # full market close; untested exit policy).
                        res = evaluate_management_action(mgmt, bridge, int(tkt),
                                                         dry_run=DRY_RUN)
                        # Commit our view ONLY if the broker accepted. A rejected
                        # modify/partial used to set executed=True → the watchdog
                        # marked breakeven/TP as done while MT5 was untouched, and
                        # never retried the move that protects the trade.
                        if res.get('executed'):
                            tracked[tkt_s]['events'].append(f"مدیریت: {mgmt['action']} ({mgmt.get('reason','')})")
                            log(f'MGMT #{tkt} {mgmt["action"]} -> ok')
                            if mgmt['action'] == 'move_stop_to_breakeven':
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
                                # A rejected breakeven/trail move means the trade
                                # is still running on its ORIGINAL stop — the
                                # retry loop keeps trying every 5s, but the
                                # operator must know NOW, not at close report.
                                send_telegram(f'⚠️ مدیریت رد شد #{tkt}: {mgmt.get("action")}\n'
                                              f'{str(res["error"])[:120]}\n'
                                              f'اتصال/SL اصلی هنوز فعال — تلاش مجدد خودکار')

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
                send_telegram(f'⚠️ Watchdog: ۱۰ خطای متوالی\n{err[:150]}')
            time.sleep(10 if errors < 5 else 30)


if __name__ == '__main__':
    main()
