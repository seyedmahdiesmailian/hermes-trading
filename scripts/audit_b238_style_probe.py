"""b238 part 2: why is style None in the lab trade log?

The live path reaches `market_entry_now` and carries `execution_style`.
The lab calls the SAME `evaluate_monitor_cycle` so it should too.
Reproduce one lab cycle directly to see what comes back.
"""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from datetime import datetime, timezone
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.candles import fetch_candles
from engines.context import build_plan_context, apply_bias_geometry
from engines.plan import apply_smc_merge, build_plan_from_context, evaluate_monitor_cycle
from engines.smc import smc_analyse

bc = BridgeClient()
m5 = fetch_candles(bc, 'XAUUSD', 'M5', 1600)
h1 = fetch_candles(bc, 'XAUUSD', 'H1', 200)
h4 = fetch_candles(bc, 'XAUUSD', 'H4', 200)
print('fetched', len(m5), len(h1), len(h4))

found = 0
styles = {}
for i in range(1200, len(m5) - 1):
    now = datetime.now(timezone.utc)
    row = m5[i]
    m5w = m5[:i + 1]
    hour = now.hour
    session = 'london' if 7 <= hour < 15 else ('newyork' if 15 <= hour < 21 else 'asia')
    depth = 120
    try:
        ctx = build_plan_context(m5w[-depth:], h1[-80:], h4[-80:], session)
        smc_result = smc_analyse(m5w[-depth:], now=now, h1_rows=h1[-80:])
        merged = apply_smc_merge(ctx, smc_result) if False else {}
    except Exception as e:
        print('ctx err', e)
        break
    # mirror the lab: merge is applied in-place by apply_smc_merge(ctx, merged,...)
    try:
        apply_smc_merge(ctx, merged, entry_close=float(row.get('close', 0) or 0),
                        rebuild=apply_bias_geometry)
    except Exception as e:
        print('merge err', e)
        break
    plan = build_plan_from_context(ctx, now=now)
    d = evaluate_monitor_cycle(plan, price=float(row['close']), now=now, m5_rows=m5w)
    if d.get('action') == 'market_entry_now':
        found += 1
        st = d.get('execution_style')
        styles[st] = styles.get(st, 0) + 1
        if found <= 3:
            print('ENTRY', found, '| style =', repr(st), '| bias', plan.get('bias'),
                  '| grade', (plan.get('quality') or {}).get('setup_grade'))
print('entries found:', found)
print('style histogram:', styles)
