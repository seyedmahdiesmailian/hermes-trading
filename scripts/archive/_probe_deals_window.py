#!/usr/bin/env python3
"""Full deal reconstruction for the two losing sells (server time = UTC+3:30)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import env_loader; env_loader.load_dotenv('.env')
from datetime import datetime, timedelta
from bridge_client import BridgeClient

b = BridgeClient()
now_server = datetime.utcnow() + timedelta(hours=3, minutes=30)
frm = now_server - timedelta(hours=8)
res = b.get_history_deals(days=1)  # legacy
# call raw endpoint with explicit window
raw = b._get('/api/history/deals', {'from': frm.strftime('%Y.%m.%d %H:%M:%S'),
                                    'to': (now_server + timedelta(days=1)).strftime('%Y.%m.%d %H:%M:%S')})
print('raw keys:', list(raw) if isinstance(raw, dict) else type(raw))
deals = raw.get('data') if isinstance(raw, dict) else None
if isinstance(deals, dict):
    deals = deals.get('deals')
if deals is None and isinstance(raw, dict):
    deals = raw.get('deals')
print('n:', len(deals or []))
for x in (deals or []):
    print('  ', x.get('time'), x.get('type'), x.get('volume'), x.get('price'),
          'pnl=', x.get('profit'), 'comm=', x.get('commission'),
          'pos=', x.get('position_id'), 'entry=', x.get('entry'), '|', x.get('comment'))
