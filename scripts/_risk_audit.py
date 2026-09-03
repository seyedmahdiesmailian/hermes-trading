#!/usr/bin/env python3
import json
import os
import sys
import statistics
import datetime
import glob
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing -> local fallback
load_dotenv(os.path.join(_ROOT, '.env'))
os.chdir(_ROOT)  # b67-harvest: these probes glob data/... relative paths
from bridge_client import BridgeClient
def num(x):
    try: return float(x)
    except Exception: return None

c = BridgeClient(token=os.getenv('HERMES_BRIDGE_TOKEN'))
acct = c.get_account()
bal = num(acct.get('balance')) or num((acct.get('data') or {}).get('balance')) or 4982.0
h = c.get_history_deals('XAUUSD', 60)
hd = h.get('data') if isinstance(h, dict) else h
pos = {}
for d in hd or []:
    pid = d.get('position_id')
    e = pos.setdefault(pid, dict(pnl=0.0, vol=0.0, side='', t=None))
    e['pnl'] += num(d.get('profit')) or 0.0
    if num(d.get('volume')): e['vol'] = num(d['volume'])
    if d.get('type') in ('BUY','SELL') and not e['side']: e['side'] = d['type']
    ts = num(d.get('time'))
    if ts and (e['t'] is None or ts < e['t']): e['t'] = ts
closed = {k: v for k, v in pos.items() if abs(v['pnl']) > 1e-9}

# planned risk per position from plan_history matched by time
plans = []
for f in glob.glob('data/xau_plan/plan_history/*.json'):
    try: p = json.load(open(f))
    except Exception: continue
    if not isinstance(p, dict) or not p.get('execution'): continue
    z = p.get('zones') or {}
    bull = p.get('bias') == 'bullish'
    ent = num(z.get('long_entry_high')) if bull else num(z.get('short_entry_low'))
    sl = num(p.get('invalidation'))
    if not (ent and sl): continue
    plans.append(dict(pid=p['plan_id'], ts=p.get('created_at',''), ent=ent, sl=sl,
                      risk=abs(ent-sl), atr=num(p.get('atr')) or 0))

print('=== RISK PER TRADE (broker-confirmed) ===')
print('balance now: %.2f$   2%% = %.2f$' % (bal, bal*0.02))
rows = []
for k, v in sorted(closed.items(), key=lambda kv: kv[1]['t'] or 0):
    # find plan whose entry/sl best matches this position's deals
    best = min(plans, key=lambda p: abs(p['risk'] - abs(v['pnl'])/(v['vol']*100)) ) if plans else None
    loss_usd = -v['pnl'] if v['pnl'] < 0 else 0
    rows.append((k, v, best))
    if v['pnl'] < 0:
        dist = abs(v['pnl'])/(v['vol']*100)
        print('LOSER pos %s vol=%.2f loss=%+.2f$ -> implied stop dist=$%.2f -> %.1f%% of balance' % (
            k, v['vol'], v['pnl'], dist, 100*abs(v['pnl'])/bal))
print()
print('=== RISK BUDGET ===')
print('max single loss %% of balance: %.2f%%' % (100*max(abs(v['pnl']) for k,v,_ in rows if v['pnl']<0)/bal))
print('sum of losses = %.2f$   sum of wins = %.2f$' % (
    sum(v['pnl'] for k,v,_ in rows if v['pnl']<0), sum(v['pnl'] for k,v,_ in rows if v['pnl']>0)))
