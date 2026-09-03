import sys, os, json, statistics
sys.path.insert(0, '.')
from bridge_client import BridgeClient
def num(x):
    try: return float(x)
    except Exception: return None
c = BridgeClient(token=os.getenv('BRIDGE_TOKEN'))
h = c.get_history_deals('XAUUSD', 60)
hd = h.get('data') if isinstance(h, dict) else h
# group by position_id -> net closed P&L per position
pos = {}
for d in hd or []:
    pid = d.get('position_id') or d.get('ticket')
    pr = num(d.get('profit')) or 0.0
    e = pos.setdefault(pid, dict(pnl=0.0, vol=0.0, entry=0.0, sl=0.0, side=''))
    e['pnl'] += pr
    if num(d.get('volume')): e['vol'] = num(d['volume'])
    if d.get('type') in ('BUY','SELL') and not e['side']:
        e['side'] = d.get('type'); e['entry'] = num(d.get('price_open')) or 0
        e['sl'] = num(d.get('sl')) or 0
closed = {k: v for k, v in pos.items() if abs(v['pnl']) > 1e-9}
print('positions touched=%d  closed with P&L=%d' % (len(pos), len(closed)))
pnls = [v['pnl'] for v in closed.values()]
wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p < 0]
print('wins=%d  losses=%d  winrate=%.0f%%' % (len(wins), len(losses), 100*len(wins)/max(1,len(pnls))))
print('avg win = %+.2f$   avg loss = %+.2f$   payoff = %.2f' % (
    statistics.mean(wins) if wins else 0, statistics.mean(losses) if losses else 0,
    abs(statistics.mean(wins)/statistics.mean(losses)) if wins and losses else 0))
print('total = %+.2f$   expectancy/trade = %+.2f$' % (sum(pnls), sum(pnls)/max(1,len(pnls))))
# R multiples
rs = []
for v in closed.values():
    if v['sl'] and v['entry']:
        risk = abs(v['entry']-v['sl'])*v['vol']*100
        if risk > 0: rs.append(v['pnl']/risk)
if rs:
    print('\nR-multiples n=%d: mean=%+.2fR  median=%+.2fR  best=%+.2fR worst=%+.2fR' % (
        len(rs), statistics.mean(rs), statistics.median(rs), max(rs), min(rs)))
    print('  frac of losers that lost >1R: %.0f%%' % (100*len([r for r in rs if r < -1.0])/len(rs)))
    print('  frac of winners that won >1R: %.0f%%' % (100*len([r for r in rs if r > 1.0])/len(rs)))
print('\n=== LAST 12 CLOSED POSITIONS ===')
for k, v in sorted(closed.items(), key=lambda kv: kv[0])[-12:]:
    risk = abs(v['entry']-v['sl'])*v['vol']*100 if v['sl'] and v['entry'] else 0
    print('pos %s %-4s vol=%.2f entry=%.2f sl=%.2f  pnl=%+8.2f$  %s' % (
        k, v['side'], v['vol'], v['entry'], v['sl'], v['pnl'],
        ('%+.2fR' % (v['pnl']/risk)) if risk else ''))
