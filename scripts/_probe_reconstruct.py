#!/usr/bin/env python3
"""Reconstruct the two recent SELL positions end-to-end."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import env_loader; env_loader.load_dotenv('.env')
import csv, json
from bridge_client import BridgeClient

# 1) raw bridge response shape
b = BridgeClient()
raw = b._get('/api/history/deals', {'days': 2}) if hasattr(b, '_get') else None
print('raw shape:', type(raw), (list(raw)[:6] if isinstance(raw, dict) else str(raw)[:200]))

# 2) execution log today
print('── execution_log tail:')
try:
    rows = list(csv.DictReader(open('data/xau_plan/execution_log.csv')))
    for r in rows[-14:]:
        print('  ', {k: r.get(k) for k in list(r)[:10]})
except Exception as e:
    print('   err', e)

# 3) runtime state
try:
    rs = json.load(open('data/xau_plan/runtime_state.json'))
    print('── runtime_state keys:', list(rs)[:15])
    print(json.dumps(rs, ensure_ascii=False)[:1200])
except Exception as e:
    print('runtime err', e)
