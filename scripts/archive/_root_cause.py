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

plans = []
for f in glob.glob('data/xau_plan/plan_history/*.json'):
    try: p = json.load(open(f))
    except Exception: continue
    if not isinstance(p, dict) or not p.get('execution'): continue
    z = p.get('zones') or {}
    bull = p.get('bias') == 'bullish'
    ent = num(z.get('long_entry_high')) if bull else num(z.get('short_entry_low'))
    sl = num(p.get('invalidation'))
    tg = [num(t) for t in (p.get('targets') or [])]
    tg = [t for t in tg if t]
    if not (ent and sl and tg): continue
    risk = abs(ent - sl)
    fin = max(tg) if bull else min(tg)
    t1 = min(tg) if bull else max(tg)
    plans.append(dict(pid=p['plan_id'], ts=p.get('created_at', ''), bias=p['bias'],
        ent=ent, sl=sl, risk=risk, rr=abs(fin - ent) / risk if risk else 0,
        rr1=abs(t1 - ent) / risk if risk else 0, atr=num(p.get('atr')),
        grade=(p.get('quality') or {}).get('smc_confidence'), tg=tg))

plans.sort(key=lambda x: x['ts'])
print('=== EXECUTED PLANS: planned geometry (n=%d) ===' % len(plans))
for p in plans[-16:]:
    print('%s %-8s ent=%.2f sl=%.2f risk=$%.2f ATR=%.2f risk/ATR=%.1f  RRfinal=%.2f RRt1=%.2f' % (
        p['ts'][:16], p['bias'], p['ent'], p['sl'], p['risk'], p['atr'] or 0,
        (p['risk'] / p['atr']) if p['atr'] else 0, p['rr'], p['rr1']))

if plans:
    rrs = [p['rr'] for p in plans]
    print('\nPLANNED RR: median=%.2f mean=%.2f min=%.2f  frac<1.5=%.0f%%' % (
        statistics.median(rrs), statistics.mean(rrs), min(rrs),
        100 * len([r for r in rrs if r < 1.5]) / len(rrs)))

# ---- realized ----
c = BridgeClient(token=os.getenv('HERMES_BRIDGE_TOKEN'))
h = c.get_history_deals('XAUUSD', 60)
hd = h.get('data') if isinstance(h, dict) else h
deals = [d for d in (hd or []) if num(d.get('profit')) is not None]
deals.sort(key=lambda d: d.get('time', ''))
print('\n=== REALIZED (last 20 exits) ===')
tot = win = loss = 0.0
for d in deals[-20:]:
    pr = num(d.get('profit')); vol = num(d.get('volume')) or 0
    ent = num(d.get('price_open')) or 0; sl = num(d.get('sl')) or 0
    rsk = abs(ent - sl) * vol * 100 if sl else 0
    print('%s %-4s vol=%.2f price=%.2f profit=%+.2f  risk$=%.2f  R=%+.2f' % (
        str(d.get('time'))[:16], d.get('type'), vol, ent, pr, rsk,
        (pr / rsk) if rsk else 0))
print('\nALL deals profit sum=%+.2f  wins=%d losses=%d' % (
    sum(num(d.get('profit')) or 0 for d in deals),
    len([d for d in deals if (num(d.get('profit')) or 0) > 0]),
    len([d for d in deals if (num(d.get('profit')) or 0) < 0])))
