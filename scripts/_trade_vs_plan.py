import sys, os, json, glob, datetime
sys.path.insert(0, '.')

# map every closed deal to its plan file so we can compare PLANNED geometry
# vs REALIZED outcome.
plans = {}
for f in glob.glob('data/xau_plan/plan_history/*.json'):
    try:
        p = json.load(open(f))
    except Exception:
        continue
    ex = p.get('execution') or {}
    tk = ex.get('ticket')
    if tk:
        plans[int(tk)] = (f, p)
print('plans with tickets:', len(plans))

from bridge_client import BridgeClient
c = BridgeClient(token=os.getenv('BRIDGE_TOKEN'))
h = c.get_history_deals('XAUUSD', 60)
pos = {}
for x in h['data']:
    pos.setdefault(x['position_id'], []).append(x)

rows = []
for pid, ds in pos.items():
    ds.sort(key=lambda z: z['time'])
    ins = [z for z in ds if z['entry'] == 0]
    outs = [z for z in ds if z['entry'] == 1]
    i = ins[0]
    pnl = sum(z['profit'] + z['commission'] + z['swap'] for z in outs)
    sl_dist = abs(i['price'] - (outs[0].get('sl') or i['price']))
    rows.append({
        'pid': pid, 'side': i['type'], 'entry': i['price'],
        'vol': sum(z['volume'] for z in ins),
        'pnl': round(pnl, 2),
        'open': datetime.datetime.utcfromtimestamp(i['time']).strftime('%m-%d %H:%M'),
        'dur_min': round((outs[-1]['time'] - i['time']) / 60) if outs else None,
        'n_out': len(outs),
        'exit_px': outs[-1]['price'] if outs else None,
    })
rows.sort(key=lambda r: r['open'])

print('\n%-12s %-4s %-8s %-6s %-8s %-6s %-7s %s' % ('open', 'side', 'entry', 'vol', 'pnl$', 'min', 'exits', 'plan geometry'))
for r in rows:
    f_p = plans.get(r['pid'])
    g = ''
    if f_p:
        p = f_p[1]
        ex = p.get('execution') or {}
        e = ex.get('entry_price') or p.get('entry_zone')
        sl = ex.get('stop_loss') or p.get('stop_loss')
        tp = ex.get('take_profit') or (p.get('targets') or [None])[-1]
        try:
            rr = abs(float(tp) - float(e)) / abs(float(e) - float(sl))
            g = 'SL=%.1f TP=%.1f RR=%.2f grade=%s' % (float(e) - float(sl), float(tp) - float(e), rr, p.get('grade'))
        except Exception:
            g = 'geom?'
        r['risk_mult'] = (p.get('execution') or {}).get('risk_pct')
    print('%-12s %-4s %-8s %-6.2f %+8.2f %-6s %-7d %s' % (
        r['open'], r['side'], r['entry'], r['vol'], r['pnl'],
        r['dur_min'], r['n_out'], g))

# quick aggregates
w = [r for r in rows if r['pnl'] > 0]
l = [r for r in rows if r['pnl'] < 0]
print('\nW=%d avg=%.2f | L=%d avg=%.2f | ratio=%.2f | expectancy/trade=%.2f' % (
    len(w), sum(r['pnl'] for r in w) / len(w), len(l),
    sum(r['pnl'] for r in l) / len(l),
    abs(sum(r['pnl'] for r in w) / sum(r['pnl'] for r in l)),
    sum(r['pnl'] for r in rows) / len(rows)))
print('trades closed in <=2min:', [r['pid'] for r in rows if r['dur_min'] is not None and r['dur_min'] <= 2])
print('losses on <=2min trades: %.2f' % sum(r['pnl'] for r in rows if r['dur_min'] is not None and r['dur_min'] <= 2 and r['pnl'] < 0))
