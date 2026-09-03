import sys, os, json, glob, datetime
sys.path.insert(0, '.')
from bridge_client import BridgeClient
c = BridgeClient(token=os.getenv('BRIDGE_TOKEN'))

h = c.get_history_deals('XAUUSD', 60)
hd = h.get('data') if isinstance(h, dict) else h
deals = [d for d in (hd or []) if d.get('entry') in ('in', 'out')]

# group by position_id
pos = {}
for d in deals:
    pid = d.get('position_id') or d.get('order')
    pos.setdefault(pid, []).append(d)

trades = []
for pid, ds in pos.items():
    ins = [d for d in ds if d.get('entry') == 'in']
    outs = [d for d in ds if d.get('entry') == 'out']
    if not ins:
        continue
    i = ins[0]
    profit = sum(d.get('profit', 0) + d.get('commission', 0) + d.get('swap', 0) for d in outs)
    vol_in = sum(d.get('volume', 0) for d in ins)
    vol_out = sum(d.get('volume', 0) for d in outs)
    t0 = min(d.get('time', 0) for d in ds)
    t1 = max(d.get('time', 0) for d in outs) if outs else None
    trades.append({
        'pid': pid, 'side': i.get('type'), 'entry': i.get('price'),
        'vol_in': vol_in, 'vol_out': vol_out,
        'profit': round(profit, 2),
        'open': datetime.datetime.utcfromtimestamp(t0).strftime('%m-%d %H:%M') if t0 else '?',
        'close': datetime.datetime.utcfromtimestamp(t1).strftime('%m-%d %H:%M') if t1 else 'OPEN',
        'mins': round((t1 - t0) / 60) if (t0 and t1) else None,
        'reason': (outs[0].get('reason') if outs else ''),
        'comment': i.get('comment', ''),
    })
trades.sort(key=lambda t: t['open'])
for t in trades:
    print(json.dumps(t, ensure_ascii=False))
