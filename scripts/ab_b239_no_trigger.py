"""b239 part 9 — A/B: drop m5_confirmation from the entry trigger.

Part 8: when the 3-consecutive-close trigger FIRES, forward move is
+0.293 ATR in the trade's direction; when it does NOT fire, +0.567 ATR —
nearly 2x better. The trigger is anti-predictive: it filters out the good
entries. Live today saw exactly this — both pullback entries fired on the
trigger and landed at the TOP of the zone.

Run the live-parity funnel twice, identical data:
  BASE = HEAD (trigger enforced)
  FIX  = HEAD with m5_confirmation short-circuited to True (zone-touch entry)

The guard rails stay in place (RR floor, zone requirement, plan bias). The
only thing varied is whether 3 rising closes are required to pull the
trigger. If the funnel improves, the trigger is the defect.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest
from engines import orchestrator as O

bc = BridgeClient()
_orig = O.m5_confirmation


def run_leg(skip_trigger):
    O.m5_confirmation = (lambda rows, bias: True) if skip_trigger else _orig
    try:
        return run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=3000, min_rr=1.5)
    finally:
        O.m5_confirmation = _orig


base = run_leg(False)
fix = run_leg(True)

canary = sum(1 for t in base['trade_log'] if t.get('style') == 'pullback_continuation')
canary_fix = sum(1 for t in fix['trade_log'] if t.get('style') == 'pullback_continuation')
print(f"canary: base pullback trades={canary}  fix={canary_fix}")


def summary(label, res):
    tl = res['trade_log']
    net = sum(float(t.get('pnl') or 0) for t in tl)
    wins = sum(1 for t in tl if float(t.get('pnl') or 0) > 0)
    rrs = []
    for t in tl:
        ent, sl = float(t['entry']), float(t.get('orig_sl') or 0)
        tp = float(t.get('exit') or 0)
        if sl and tp and abs(ent - sl) > 0:
            rrs.append(abs(tp - ent) / abs(ent - sl))
    worst = min(rrs) if rrs else 0
    mean = sum(rrs) / len(rrs) if rrs else 0
    print(f"\n{label}\n  trades={len(tl)}  WR={100*wins/max(1,len(tl)):.1f}%"
          f"  net={net:+.2f}  worstR={worst:.2f}  meanR={mean:.2f}")
    return {'trades': len(tl), 'net': round(net, 2),
            'wr': round(100 * wins / max(1, len(tl)), 1),
            'worstR': round(worst, 2), 'meanR': round(mean, 2)}


sb = summary('BASE (m5 trigger enforced)', base)
sf = summary('FIX (zone-touch entry)', fix)
print(f"\ndelta: trades {sf['trades']-sb['trades']:+d}  net {sf['net']-sb['net']:+.2f}  meanR {sf['meanR']-sb['meanR']:+.2f}")

json.dump({'base': sb, 'fix': sf},
          open('data/backtest/b239_no_trigger.json', 'w'), indent=1)
print('saved data/backtest/b239_no_trigger.json')
