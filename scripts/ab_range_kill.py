#!/usr/bin/env python3
"""A/B the range-kill confidence threshold on the cached robustness dataset.
Baseline 0.35 (live) vs relaxed 0.20. Same funnel, same data, same gates."""
import os, sys, json
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

from pathlib import Path
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

data = json.loads((Path(_ROOT) / 'data/backtest/robustness_data.json').read_text())
b = BridgeClient()
WINDOW = 500
m15 = data['M15']
n = len(m15) // WINDOW
print(f"{len(m15)} bars -> {n} windows")
for conf in (0.35, 0.20):
    tot_t = tot_w = tot_l = 0; tot_pnl = 0.0; prof = 0
    for k in range(n):
        seg = m15[k*WINDOW:(k+1)*WINDOW]
        t_end = seg[-1]['time']
        sl = {'M15': seg,
              'H1': [r for r in data['H1'] if r['time'] <= t_end][-WINDOW//12-48:],
              'H4': [r for r in data['H4'] if r['time'] <= t_end][-WINDOW//240-20:]}
        r = run_backtest(b, count=WINDOW, data=sl, range_kill_conf=conf)
        if not r.get('ok'): continue
        tot_t += r['trades']; tot_w += r['wins']; tot_l += r['losses']; tot_pnl += r['net_pnl']
        if r['net_pnl'] > 0: prof += 1
    wr = tot_w / max(1, tot_w + tot_l) * 100
    print(f"range_kill_conf={conf}: trades={tot_t} WR={wr:.0f}% pnl={tot_pnl:+.0f}$ profitable_windows={prof}/{n}")
