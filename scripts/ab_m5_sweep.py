#!/usr/bin/env python3
"""A/B optimization sweep on the LIVE entry timeframe (M5), cached dataset.

Motivation (2026-09-01): the -105$ SL on #103649120 came from an
aggressive_discount_entry (no trigger, price 0.75 ATR below value_low).
The earlier aggressive-path A/B (scripts/ab_aggressive_entry.py) ran on M15
while live enters on M5 — the funnel sees different bars, so the verdict
must be re-measured at live parity before touching live gates.

Configs swept (all on the SAME byte-identical M5/H1/H4 dataset):
  A  baseline (live as-is)
  B  exclude aggressive_discount only
  C  exclude all aggressive_*
  D  min_rr 2.0
  E  breakeven_at_r 0.75
  F  breakeven_at_r 1.0
  G  min_rr 2.0 + BE 0.75
  H  exclude aggressive_value + aggressive_discount (keep premium)

Read-only: never touches order endpoints. Usage:
  python3 scripts/ab_m5_sweep.py [data_file]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from env_loader import load_dotenv
load_dotenv(ROOT / '.env')

from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'data/backtest/robustness_data_M5.json'
OUT = ROOT / 'data/backtest/ab_m5_sweep_results.json'

CONFIGS = [
    ("A_baseline",        dict()),
    ("B_no_aggr_disc",    dict(exclude_styles=["aggressive_discount"])),
    ("C_no_aggr_all",     dict(exclude_styles=["aggressive"])),
    ("D_minrr2",          dict(min_rr=2.0)),
    ("E_be075",           dict(breakeven_at_r=0.75)),
    ("F_be10",            dict(breakeven_at_r=1.0)),
    ("G_rr2_be075",       dict(min_rr=2.0, breakeven_at_r=0.75)),
    ("H_no_disc_no_val",  dict(exclude_styles=["aggressive_discount", "aggressive_value"])),
]


def summarize(res: dict) -> dict:
    t = res.get('trade_log', [])
    pnls = [x['pnl'] for x in t]
    eq = 0.0
    peak = 0.0
    maxdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
    decided = res.get('wins', 0) + res.get('losses', 0)
    return {
        'trades': res.get('trades', 0),
        'wins': res.get('wins', 0), 'losses': res.get('losses', 0),
        'scratches': res.get('scratches', 0),
        'net': res.get('net_pnl', 0),
        'wr_decided': round(res.get('wins', 0) / decided, 3) if decided else 0,
        'avg': round(sum(pnls) / len(pnls), 2) if pnls else 0,
        'max_loss': min(pnls) if pnls else 0,
        'maxdd': round(maxdd, 2),
    }


def main() -> None:
    data = json.loads(DATA.read_text())
    print(f"data: M5={len(data['M5'])} bars")
    bridge = BridgeClient()
    out = {}
    for label, kw in CONFIGS:
        res = run_backtest(bridge, timeframe='M5', data=data, **kw)
        s = summarize(res)
        out[label] = {'kwargs': {k: v for k, v in kw.items()}, **s}
        print(f"{label:20s} n={s['trades']:3d} WR={s['wr_decided']:5.1%} "
              f"net={s['net']:+8.2f} avg={s['avg']:+6.2f} maxdd={s['maxdd']:7.2f} "
              f"maxloss={s['max_loss']:+7.2f}")
        if label == 'A_baseline':
            # per-style attribution on baseline
            styles = {}
            for t in res.get('trade_log', []):
                st = str(t.get('style'))
                d = styles.setdefault(st, {'n': 0, 'pnl': 0.0, 'w': 0, 'l': 0})
                d['n'] += 1
                d['pnl'] = round(d['pnl'] + t['pnl'], 2)
                d['w'] += 1 if t['pnl'] > 0 else 0
                d['l'] += 1 if t['pnl'] < 0 else 0
            out['style_attribution'] = styles
            print('  per-style:')
            for k, v in sorted(styles.items(), key=lambda kv: -kv[1]['pnl']):
                print(f"    {k:32s} n={v['n']:3d} net={v['pnl']:+8.2f} "
                      f"WR={v['w']/max(v['n'],1):5.1%}")
            Path(ROOT / 'data/backtest/ab_m5_sweep_baseline_trades.json').write_text(
                json.dumps(res.get('trade_log', []), indent=1))
    OUT.write_text(json.dumps(out, indent=2))
    print(f"saved -> {OUT}")


if __name__ == '__main__':
    main()
