#!/usr/bin/env python3
"""b67 probe (READ-ONLY, no network, no orders): feed the bridge error/legacy
envelope shapes through EVERY real consumer of the account/tick/rates/deals
replies and report which ones return a WRONG ANSWER rather than failing loud.

b66-follow-up fixed /api/positions only; the side finding said the same
hand-rolled read sits on the other four envelopes. This probe measures it.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# READ-ONLY GUARANTEE: redirect the whole state tree into a throwaway dir
# before importing anything that touches it, so a probe run can never write
# production kill_switch_state.json / performance_state.json (the b39 lesson).
from engines import paths as _paths  # noqa: E402
_paths.set_data_root(tempfile.mkdtemp(prefix='b67_probe_'))

import hermes_runtime as hr  # noqa: E402
from engines import macro_snapshot  # noqa: E402

# ---- the shapes bridge_client._get() can actually hand back -----------------
# 1. HTTP 401 with a non-JSON body (auth blip / token missing)
E401 = {'ok': False, 'error': 'HTTP_401', 'data': {'raw': '<html>401 Unauthorized</html>'}}
# 2. HTTP 401 whose body IS json with 2+ keys (MT5 error page as json)
E401_JSON = {'ok': False, 'error': 'HTTP_401',
             'data': {'error': 'unauthorized', 'message': 'bad token'}}
# 3. MT5 itself down: server returns ok=false + HTTP 500 -> _get wraps
E500 = {'ok': False, 'error': 'HTTP_500', 'data': {'ok': False, 'error': "['Common::LastError']"}}
# 4. connection refused (bridge process dead) - NO data key at all
DOWN = {'ok': False, 'error': 'HTTPConnectionPool(host=...)'}
# 5. legacy/alternate build: bare list wrapped by _get
LEGACY_LIST = {'ok': True, 'data': [{'time': 1, 'open': 1.0, 'high': 2.0, 'low': 0.5,
                                     'close': 1.5, 'tick_volume': 10}]}
# 6. the v2 server's GOOD shapes
GOOD_RATES = {'ok': True, 'data': [dict(LEGACY_LIST['data'][0], time=i) for i in range(30)]}
GOOD_ACCOUNT = {'ok': True, 'balance': 4982.77, 'equity': 4990.0, 'margin': 100.0,
                'margin_free': 4890.0, 'login': 10382667, 'currency': 'USD'}
GOOD_TICK = {'ok': True, 'symbol': 'XAUUSD', 'ask': 3610.5, 'bid': 3610.3,
             'last': 3610.4, 'volume': 12, 'time': 1789000000}
GOOD_DEALS = {'ok': True, 'count': 2, 'data': [
    {'ticket': 1, 'order': 1, 'position_id': 555, 'entry': 0, 'type': 'BUY',
     'volume': 0.05, 'price': 3600.0, 'profit': 0.0, 'swap': 0.0, 'commission': -0.2,
     'time': 1788990000, 'comment': 'Hermes'},
    {'ticket': 2, 'order': 1, 'position_id': 555, 'entry': 1, 'type': 'SELL',
     'volume': 0.05, 'price': 3610.0, 'profit': 1.83, 'swap': 0.0, 'commission': -0.2,
     'time': 1788999000, 'comment': 'Hermes'},
]}

SHAPES = {'401-html': E401, '401-json2keys': E401_JSON, '500-mt5': E500,
          'bridge-down': DOWN}

findings = []


def note(area, shape, result, verdict, why):
    findings.append((area, shape, result, verdict, why))
    print(f"[{verdict:5}] {area:34} {shape:14} -> {result}  ({why})")


print("=== 1. hermes_runtime._data_list (rates) ===")
for name, s in SHAPES.items():
    try:
        r = hr._data_list(s)
        note('rates/_data_list', name, f'len={len(r)}', 'ok', 'empty list')
    except Exception as e:
        note('rates/_data_list', name, f'{type(e).__name__}', 'BAD', str(e)[:60])

print("\n=== 2. hermes_runtime._account_obj (account) ===")
for name, s in list(SHAPES.items()) + [('v2-good', GOOD_ACCOUNT)]:
    try:
        a = hr._account_obj(s)
        note('account/_account_obj', name,
             f'balance={a.balance} equity={a.equity} mf={a.margin_free} m={a.margin}',
             'ok' if (name == 'v2-good' or a.balance == 0) else 'BAD', '')
    except Exception as e:
        note('account/_account_obj', name, f'{type(e).__name__}', 'BAD', str(e)[:60])

print("\n=== 3. hermes_runtime._tick_price / _tick_obj ===")
for name, s in list(SHAPES.items()) + [('v2-good', GOOD_TICK)]:
    try:
        p = hr._tick_price(s)
        t = hr._tick_obj(s)
        note('tick/_tick_price', name, f'price={p} ask={t.ask} bid={t.bid}',
             'ok', '')
    except Exception as e:
        note('tick/_tick_price', name, f'{type(e).__name__}', 'BAD', str(e)[:60])

print("\n=== 4. THE POLICY CONSEQUENCE: what do the gates conclude on a 401? ===")
from engines.risk import assess_account_policy, compute_performance_state  # noqa: E402
from engines.kill_switch import check_kill_switch  # noqa: E402

for name, s in SHAPES.items():
    a = hr._account_obj(s)
    perf = compute_performance_state({'day': '1999-01-01'}, '2026-09-03', a.balance, [])
    pol = assess_account_policy(a.balance, a.equity, a.margin_free, a.margin,
                               float(perf['daily_pnl']), int(perf['loss_streak']), 0)
    kill = check_kill_switch(balance=a.balance, equity=a.equity,
                             daily_pnl=-500.0, consecutive_losses=9,
                             margin_free=a.margin_free, margin=a.margin,
                             now=datetime(2026, 9, 3, tzinfo=timezone.utc))
    note('policy on error shape', name,
         f'trade_allowed={pol["trade_allowed"]} regime={pol["regime"]} '
         f'kill_halted={kill["halted"]}({kill["reason"]})',
         'BAD' if pol['trade_allowed'] and not kill['halted'] else 'ok',
         'daily-loss -500$ and 9 straight losses IGNORED' if pol['trade_allowed'] and not kill['halted'] else '')

print("\n=== 5. sizing consequence (does something still block the entry?) ===")
from engines.auto_executor import evaluate_proposal  # noqa: E402

BP = {'side': 'SELL', 'entry_price': 3610.0, 'sl': 3620.0, 'tp': 3580.0, 'symbol': 'XAUUSD'}
for name, s in SHAPES.items():
    a = hr._account_obj(s)
    pol = assess_account_policy(a.balance, a.equity, a.margin_free, a.margin, -500.0, 9, 0)
    perf = compute_performance_state({'day': '1999-01-01'}, '2026-09-03', a.balance, [])
    res = evaluate_proposal({'blueprint': BP, 'execution_style': 'pullback'},
                            pol, perf, {'quality': {'grade': 'A'}}, bridge=None)
    note('evaluate_proposal', name, f"execute={res.get('execute')} reason={res.get('reason')}",
         'ok' if not res.get('execute') else 'BAD', 'blocked only by SIZING, not by a gate'
         if not res.get('execute') and 'sizing' in str(res.get('reason')) else '')

print("\n=== 6. position_daemon.realized_pnl_usd (deals) ===")
import position_daemon as pd  # noqa: E402


class FakeBridge:
    def __init__(self, resp):
        self.resp = resp

    def get_history_deals(self, symbol='XAUUSD', days=7):
        return self.resp

    def get_rates(self, symbol='XAUUSD', timeframe='H1', count=100):
        return self.resp


for name, s in list(SHAPES.items()):
    got = pd.realized_pnl_usd(FakeBridge(s), 555)
    note('realized_pnl_usd', name, f'{got}', 'ok',
         'None -> caller falls back to FLOATING pnl (the b44 bug it replaced)')
got = pd.realized_pnl_usd(FakeBridge(GOOD_DEALS), 555)
note('realized_pnl_usd', 'v2-good', f'{got}', 'ok', '1.83-0.2-0.2=1.43 expected')

print("\n=== 7. engines.learning.journal (deals) ===")
from engines import learning  # noqa: E402
import inspect  # noqa: E402
src = inspect.getsource(learning.journal)
print('  journal guards on ok:', "r.get('ok')" in src or 'get("ok")' in src)
for name, s in SHAPES.items():
    try:
        deals = s.get('data', s.get('deals', [])) or []
        n = 0
        for d in deals:
            n += int(d.get('entry', 1) if str(d.get('entry', 1)).isdigit() else 1)
        note('journal deals loop', name, f'iterated {len(deals)} items', 'ok', '')
    except Exception as e:
        note('journal deals loop', name, f'{type(e).__name__}', 'BAD', str(e)[:70])

print("\n=== 8. macro_snapshot rows reads (no ok check, no list check) ===")
for name, s in SHAPES.items():
    rows = s.get('data', []) if isinstance(s, dict) else []
    try:
        _ = [float(x['high']) for x in rows]
        note('macro htf rows', name, f'len={len(rows)} -> no crash', 'ok', '')
    except Exception as e:
        note('macro htf rows', name, f'{type(e).__name__}', 'BAD', str(e)[:70])
# the 401-json2keys shape reaching rows[-2]
try:
    rows = E401_JSON.get('data', [])
    if len(rows) >= 2:
        prev = float(rows[-2].get('close', 0) or 0)
        note('macro dxy rows[-2]', '401-json2keys', f'prev={prev}', 'ok', '')
    else:
        note('macro dxy rows[-2]', '401-json2keys', f'len={len(rows)} skipped', 'ok', '')
except Exception as e:
    note('macro dxy rows[-2]', '401-json2keys', f'{type(e).__name__}', 'BAD', str(e)[:70])

print("\n=== 9. spread gate on the plan path (hermes_runtime cycle) ===")
for name, s in list(SHAPES.items()) + [('ask-no-bid', {'ok': True, 'data': {'ask': 3610.5}}),
                                       ('bid-no-ask', {'ok': True, 'data': {'bid': 3610.3}})]:
    _td = s.get('data', s) if isinstance(s, dict) else {}
    if not isinstance(_td, dict):
        _td = {}
    try:
        spr = float(_td.get('ask') or 0) - float(_td.get('bid') or 0)
        blocked = spr > hr.MAX_ENTRY_SPREAD
        note('spread gate', name, f'spread={spr} blocked={blocked}',
             'ok' if (blocked or spr == 0.0) else 'BAD',
             'negative spread passes the gate' if spr < 0 else '')
    except Exception as e:
        note('spread gate', name, f'{type(e).__name__}', 'BAD', str(e)[:60])

print("\n=== 10. backtest_real.fetch_all_ohlc ===")
from engines.backtest_real import fetch_all_ohlc  # noqa: E402
for name, s in list(SHAPES.items()) + [('legacy-list', LEGACY_LIST)]:
    rows = fetch_all_ohlc(FakeBridge(s))
    note('fetch_all_ohlc', name, f'rows={len(rows)}', 'ok', '')

print("\n" + "=" * 70)
bad = [f for f in findings if f[3] == 'BAD']
print(f"TOTAL probes={len(findings)}  BAD={len(bad)}")
for b in bad:
    print("  BAD:", b[0], '|', b[1], '|', b[2], '|', b[4])
