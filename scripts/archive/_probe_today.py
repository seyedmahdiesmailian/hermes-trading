#!/usr/bin/env python3
"""Read-only probe: today's deals, positions, balance, journal tail."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import env_loader; env_loader.load_dotenv('.env')
import csv
from datetime import datetime, timezone
from bridge_client import BridgeClient

b = BridgeClient()
print('now UTC:', datetime.now(timezone.utc).strftime('%H:%M:%S'))

acc = b.get_account()
if isinstance(acc, dict):
    d = acc.get('data') or acc
    print('balance:', d.get('balance'), '| equity:', d.get('equity'))

pos = b.get_positions()
plist = pos if isinstance(pos, list) else (pos or {}).get('positions', [])
print('open positions:', len(plist))
for p in plist:
    print('  ', {k: p.get(k) for k in ('ticket', 'type', 'volume', 'price_open',
                                       'sl', 'tp', 'time', 'profit')})

deals = b.get_history_deals(days=1)
if isinstance(deals, dict):
    deals = deals.get('deals') or []
print('deals(1d):', len(deals))
for x in deals[-30:]:
    print('  ', x.get('time'), x.get('type'), x.get('volume'), x.get('price'),
          'pnl=', x.get('profit'), 'comm=', x.get('commission'),
          'pos=', x.get('position_id'), '|', x.get('comment'))

print('── journal tail:')
try:
    rows = list(csv.DictReader(open('data/xau_plan/trade_journal.csv')))
    for r in rows[-6:]:
        print('  ', {k: r.get(k) for k in list(r)[:9]})
except Exception as e:
    print('   journal err:', e)
