"""b239 part 18 — the realized-R gap: be_lock_r and the trailing stop.

The funnel ships ~1.10R realized against a 1.5R admission floor. Where does
the other 0.4R go? Two suspects, both on the exit side:

 be_lock_r (default 0.5): after TP1 the stop locks at entry+0.5R. Any
   retracement then exits at 0.5R instead of the full target. That is a
   direct R conversion: a trade that "was" 1.5R becomes 0.5R+0.5R(partial).
 trail_after_partial (default 0.0): the live system trails after the
   partial, but the funnel default is 0.0 = no trail.

Sweep be_lock_r in {0.0 (live plain BE), 0.25, 0.5 (current), 0.75, 1.0}
and trail_after_partial in {0.0, 0.5, 1.0}. Report realized mean R and net
so a candidate must win on both to be considered.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

bc = BridgeClient()
out = {}
for be in (0.0, 0.25, 0.5, 0.75, 1.0):
    r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=3000, min_rr=1.5,
                     be_lock_r=be)
    tl = r['trade_log']
    net = sum(float(t.get('pnl') or 0) for t in tl)
    wins = sum(1 for t in tl if float(t.get('pnl') or 0) > 0)
    rrs = []
    for t in tl:
        ent, sl = float(t['entry']), float(t.get('orig_sl') or 0)
        tp = float(t.get('exit') or 0)
        if sl and tp and abs(ent - sl) > 0:
            rrs.append(abs(tp - ent) / abs(ent - sl))
    mean_r = sum(rrs) / len(rrs) if rrs else 0
    out[f'be_{be}'] = {'trades': len(tl), 'net': round(net, 2),
                       'wr': round(100 * wins / max(1, len(tl)), 1), 'meanR': round(mean_r, 3)}
    print(f"  be_lock_r={be:<5} trades={len(tl):3d} WR={100*wins/max(1,len(tl)):5.1f}%"
          f"  net={net:+8.2f}  meanR={mean_r:5.3f}")

print()
for tr_ in (0.5, 1.0):
    r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=3000, min_rr=1.5,
                     trail_after_partial=tr_)
    tl = r['trade_log']
    net = sum(float(t.get('pnl') or 0) for t in tl)
    wins = sum(1 for t in tl if float(t.get('pnl') or 0) > 0)
    rrs = []
    for t in tl:
        ent, sl = float(t['entry']), float(t.get('orig_sl') or 0)
        tp = float(t.get('exit') or 0)
        if sl and tp and abs(ent - sl) > 0:
            rrs.append(abs(tp - ent) / abs(ent - sl))
    mean_r = sum(rrs) / len(rrs) if rrs else 0
    out[f'trail_{tr_}'] = {'trades': len(tl), 'net': round(net, 2),
                           'wr': round(100 * wins / max(1, len(tl)), 1), 'meanR': round(mean_r, 3)}
    print(f"  trail={tr_:<5} trades={len(tl):3d} WR={100*wins/max(1,len(tl)):5.1f}%"
          f"  net={net:+8.2f}  meanR={mean_r:5.3f}")

json.dump(out, open('data/backtest/b239_exit_sweep.json', 'w'), indent=1)
print('\nsaved data/backtest/b239_exit_sweep.json')
