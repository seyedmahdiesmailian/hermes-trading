"""b239 part 8 — the trigger is adverse-selected into the bad part of the zone.

Live tickets 111570069 / 111572408 entered at 4151.67 / 4154.10 in a long
zone of 4124.81-4155.77 — the TOP of the zone, while tp_levels[0] was the
zone ceiling 4155.77. The lab saw only 1 pullback trade; live saw 2, both
at the top. Why?

The entry trigger is `m5_confirmation`: 3 consecutive M5 closes moving WITH
the bias. For a BUY that is 3 rising closes — i.e. price has been RISING
into the entry zone. Rising price reaches the top of the zone. So the
trigger is statistically biased toward the worst entry location, and it is
momentum confirmation bolted onto a mean-reversion trade (the target is
the same side of the zone price is already at).

This measures it directly: for each M5 bar inside a long/short entry zone,
compute (a) whether the trigger would fire and (b) the eventual outcome as
a function of the entry's position within the zone. If trigger bars skew
to the top and top-of-zone entries underperform, the trigger is the defect.
"""
import sys, json, collections
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import fetch_all_ohlc
from engines.context import build_plan_context
from engines.orchestrator import m5_confirmation

bc = BridgeClient()
m5 = fetch_all_ohlc(bc, 'XAUUSD', 'M5', 3000)
h1 = fetch_all_ohlc(bc, 'XAUUSD', 'H1', 200)
h4 = fetch_all_ohlc(bc, 'XAUUSD', 'H4', 200)
n = len(m5)
print('M5 bars:', n)

ATR, HZN = 24, 12
pos_when_trigger, pos_when_not = [], []
all_in_zone = []

# rebuild the plan every 12 bars as the live loop does (replan cadence)
for start in range(200, n - HZN, 12):
    rows = m5[start:start + 120]
    if len(rows) < 100:
        continue
    try:
        ctx = build_plan_context(rows, h1[-80:], h4[-80:], 'london')
    except Exception:
        continue
    z = ctx['zones']
    if ctx['bias'] == 'neutral':
        continue
    for j in range(60, len(rows) - 1):
        price = float(rows[j]['close'])
        inzone = None
        if ctx['bias'] == 'bullish' and z['long_entry_low'] <= price <= z['long_entry_high']:
            inzone = ('long', z['long_entry_low'], z['long_entry_high'])
        elif ctx['bias'] == 'bearish' and z['short_entry_low'] <= price <= z['short_entry_high']:
            inzone = ('short', z['short_entry_low'], z['short_entry_high'])
        if not inzone:
            continue
        side, lo, hi = inzone
        frac = (price - lo) / (hi - lo) if hi > lo else 0.5   # 0=bottom, 1=top
        trig = m5_confirmation(rows[max(0, j - 8):j + 1], ctx['bias'])
        fwd = rows[j + 1:j + 1 + HZN]
        if not fwd:
            continue
        base = price
        end = float(fwd[-1]['close'])
        # signed drift: positive = moved in the trade's direction
        move = (end - base) if side == 'long' else (base - end)
        atr = sum(abs(float(r['high']) - float(r['low'])) for r in rows[j - ATR:j + 1]) / ATR
        if atr <= 0:
            continue
        rec = {'frac': round(frac, 3), 'trig': trig, 'move_atr': round(move / atr, 3)}
        all_in_zone.append(rec)
        (pos_when_trigger if trig else pos_when_not).append(rec)

print(f"\n=== bars inside the entry zone: {len(all_in_zone)} ===")
t = pos_when_trigger
nt = pos_when_not
print(f"  trigger fired: {len(t)}   not fired: {len(nt)}")
if t:
    mt = sum(r['move_atr'] for r in t) / len(t)
    print(f"  mean forward move (trigger on):  {mt:+.4f} ATR")
    print(f"  mean zone position (trigger on): {sum(r['frac'] for r in t)/len(t):.3f} (0=bottom,1=top)")
if nt:
    mn = sum(r['move_atr'] for r in nt) / len(nt)
    print(f"  mean forward move (trigger off): {mn:+.4f} ATR")
    print(f"  mean zone position (trigger off):{sum(r['frac'] for r in nt)/len(nt):.3f}")

# bucket by zone position
print("\n=== forward move by position within the zone (all bars) ===")
for name, lo_b, hi_b in (('bottom 0-.25', 0, .25), ('low .25-.5', .25, .5),
                         ('high .5-.75', .5, .75), ('top .75-1.0', .75, 1.01)):
    sel = [r for r in all_in_zone if lo_b <= r['frac'] < hi_b]
    if sel:
        m = sum(r['move_atr'] for r in sel) / len(sel)
        trig_rate = 100 * sum(1 for r in sel if r['trig']) / len(sel)
        print(f"  {name:14s} n={len(sel):4d}  move={m:+.4f} ATR  trigger_rate={trig_rate:5.1f}%")

json.dump({'trigger_n': len(t), 'trigger_move': round(sum(r['move_atr'] for r in t)/len(t), 4) if t else 0,
           'trigger_frac': round(sum(r['frac'] for r in t)/len(t), 3) if t else 0,
           'notrig_n': len(nt), 'notrig_move': round(sum(r['move_atr'] for r in nt)/len(nt), 4) if nt else 0,
           'notrig_frac': round(sum(r['frac'] for r in nt)/len(nt), 3) if nt else 0},
          open('data/backtest/b239_trigger_adverse.json', 'w'), indent=1)
print('\nsaved data/backtest/b239_trigger_adverse.json')
