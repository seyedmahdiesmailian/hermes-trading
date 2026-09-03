import sys, os, json, datetime
sys.path.insert(0, '.')
from bridge_client import BridgeClient
def num(x):
    try: return float(x)
    except Exception: return None
c = BridgeClient(token=os.getenv('BRIDGE_TOKEN'))
h = c.get_history_deals('XAUUSD', 60)
hd = h.get('data') if isinstance(h, dict) else h
pos = {}
for d in hd or []:
    pid = d.get('position_id') or d.get('ticket')
    e = pos.setdefault(pid, dict(pnl=0.0, vol=0.0, t=None, side=''))
    e['pnl'] += num(d.get('profit')) or 0.0
    if num(d.get('volume')): e['vol'] = num(d['volume'])
    ts = d.get('time')
    if ts and (e['t'] is None or ts < e['t']): e['t'] = ts
    if d.get('type') in ('BUY','SELL') and not e['side']: e['side'] = d['type']
closed = {k:v for k,v in pos.items() if abs(v['pnl'])>1e-9}
print('=== closed positions (time, vol, pnl) ===')
for k,v in sorted(closed.items(), key=lambda kv: kv[1]['t'] or 0):
    t = v['t']
    if isinstance(t,(int,float)): t = datetime.datetime.utcfromtimestamp(t)
    print('%s pos %s %-4s vol=%.2f pnl=%+8.2f$' % (str(t)[:16], k, v['side'], v['vol'], v['pnl']))
