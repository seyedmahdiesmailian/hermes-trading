"""b239 part 16 — sweep the confirmation length instead of removing it.

The trigger A/Bs all landed inside 101-126 (noise at n=16..53):
  base(momentum)  +106.76
  revert          +101.30   (16 trades — too few)
  none            +126.00   (+19 over base)
Removing the trigger is not clearly better than keeping it, and the b187
comment documents live losses that motivated adding it. So neither extreme
is justified.

The untested middle: the trigger is 3 consecutive closes. 3 is a literal
copied from b187, never swept. A shorter confirmation reacts earlier
(price has not run as far into the zone) and a longer one is stricter.
Sweep M5_CONFIRM_CLOSES over {1,2,3,4,5} on the same data and see whether
any length dominates cleanly, i.e. beats both neighbours, not just base.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest
from engines import orchestrator as O

bc = BridgeClient()
_orig_len = O.M5_CONFIRM_CLOSES
out = {}

for L in (1, 2, 3, 4, 5):
    O.M5_CONFIRM_CLOSES = L
    r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=3000, min_rr=1.5)
    tl = r['trade_log']
    net = sum(float(t.get('pnl') or 0) for t in tl)
    wins = sum(1 for t in tl if float(t.get('pnl') or 0) > 0)
    out[str(L)] = {'trades': len(tl), 'net': round(net, 2),
                   'wr': round(100 * wins / max(1, len(tl)), 1)}
    print(f"  closes={L}  trades={len(tl):3d}  WR={100*wins/max(1,len(tl)):5.1f}%  net={net:+8.2f}")
O.M5_CONFIRM_CLOSES = _orig_len

best = max(out.items(), key=lambda kv: kv[1]['net'])
print(f"\nbest length by net: {best[0]} -> {best[1]}")
json.dump(out, open('data/backtest/b239_confirm_sweep.json', 'w'), indent=1)
print('saved data/backtest/b239_confirm_sweep.json')
