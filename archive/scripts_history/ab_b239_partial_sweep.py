"""b239 part 17 — partial-share / TP geometry, the other half of the ticket.

Live tickets 111570069 / 111572408 exited at TP1 for +3.94 / +1.95. The
entry geometry was fixed in b238 (0.05R -> 1.55R). But the EXIT side has
its own knob never measured against live: TP_SHARES [0.5, 0.5] closes half
the position at tp_levels[0] and runs the rest to tp_levels[1].

On a 1.55R trade, is half-at-TP1 / half-at-TP2 better than a single target?
The funnel defaults partial_tp1_share=0.5 and tp1_position=0.5. Sweep both
and measure realized R, not net dollars — R is what survives the A/B
comparison being run on a differently-priced slice.

Only report an arm if it beats the default on BOTH legs tested here and
in the previous session's sweep, otherwise this is just noise fitting.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

bc = BridgeClient()
out = {}
for share in (0.0, 0.25, 0.5, 0.75, 1.0):
    r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=3000, min_rr=1.5,
                     partial_tp1_share=share)
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
    out[str(share)] = {'trades': len(tl), 'net': round(net, 2),
                       'wr': round(100 * wins / max(1, len(tl)), 1),
                       'meanR': round(mean_r, 3)}
    print(f"  partial_share={share:<5} trades={len(tl):3d} WR={100*wins/max(1,len(tl)):5.1f}%"
          f"  net={net:+8.2f}  meanR={mean_r:5.3f}")

json.dump(out, open('data/backtest/b239_partial_sweep.json', 'w'), indent=1)
print('\nsaved data/backtest/b239_partial_sweep.json')
