#!/usr/bin/env python3
"""Deep probe of the two losing SELL trades at ~10:30 UTC."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import env_loader; env_loader.load_dotenv('.env')
import json, glob
from datetime import datetime, timezone
from bridge_client import BridgeClient

b = BridgeClient()
deals = b.get_history_deals(days=3)
if isinstance(deals, dict):
    deals = deals.get('deals') or []
print('deals(3d):', len(deals))
for x in deals:
    t = str(x.get('time'))
    if '2026-08-31 1' in t or '2026-08-31 0' in t:
        print('  ', t, x.get('type'), x.get('volume'), x.get('price'),
              'pnl=', x.get('profit'), 'comm=', x.get('commission'),
              'pos=', x.get('position_id'), '|', x.get('comment'))

print('── plan history 09:00-11:00 UTC:')
for f in sorted(glob.glob('data/xau_plan/plan_history/20260831_*.json')):
    hh = os.path.basename(f)[9:15]
    if '090000' <= hh <= '110000':
        p = json.load(open(f))
        print('  ', hh, 'bias=', p.get('bias'), 'mode=', p.get('execution_mode'),
              'grade=', (p.get('quality') or {}).get('grade'),
              'id=', p.get('plan_id'))
