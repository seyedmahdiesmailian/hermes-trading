#!/usr/bin/env python3
"""b55: modern-strategy research implemented and tested on the live-parity funnel.

Three techniques from the 2025/2026 quant literature, each tested honestly
with WALK-FORWARD (train on the first 2/3 of the M5 dataset, judge only on
the unseen last 1/3 — no lookahead anywhere):

1. META-LABELING (Lopez de Prado): a secondary logistic model trained on the
   funnel's own historical trades predicts P(win) from entry-time features
   (ATR-percentile regime, volume z-score, range position, trend slope, hour
   sin/cos, grade, style, side). Trades below a probability floor are skipped.
   The primary strategy is untouched — meta only filters.

2. VOLATILITY-REGIME FILTER: skip entries when the 20-bar ATR percentile
   (vs trailing 400 bars) sits below 10% (dead tape) or above 90% (chaos).

3. ICT KILLZONE WINDOWS: entries only in London 07-10 UTC / NY 13-16 UTC.

Baseline = live config (grade-aware 0.7 ladder, spread 0.20, min_rr 1.5,
grade>=B) on the same bars. Output: ab_b55_meta_results.json. Read-only.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from env_loader import load_dotenv
load_dotenv(ROOT / '.env')

import numpy as np
from bridge_client import BridgeClient
from engines import backtest_real as br
from engines.trade_management import _partial_close_fraction

DATA = json.loads((ROOT / 'data/backtest/robustness_data_M5.json').read_text())
OUT = ROOT / 'data/backtest/ab_b55_meta_results.json'
ROWS = DATA['M5'] if isinstance(DATA, dict) else DATA
N = len(ROWS)
SPLIT = int(N * 2 / 3)
PAD = 150
GRADE_NUM = {'A+': 4, 'A': 3, 'B': 2, 'C': 1, '': 0, None: 0}

# ── filter state, set per arm before each run ──
SEG = None            # current segment rows
META = None           # (mu, sd, w) or None
META_THRESH = None
KILLZONE = False
ATRBAND = False
FEATURE_CACHE = {}


def _atr(rows, i, n=20):
    tot = cnt = 0.0
    for k in range(max(1, i - n + 1), i + 1):
        h, l, pc = rows[k]['high'], rows[k]['low'], rows[k - 1]['close']
        tot += max(h - l, abs(h - pc), abs(l - pc))
        cnt += 1
    return tot / cnt if cnt else 0.0


def features(rows, idx, sig):
    look = min(idx, 400)
    atr_now = _atr(rows, idx, 20)
    hist = [_atr(rows, j, 20) for j in range(idx - look + 1, idx + 1, 7)]
    pct = sum(1 for a in hist if a <= atr_now) / max(1, len(hist))
    t = datetime.fromtimestamp(rows[idx]['time'], tz=timezone.utc)
    vols = [rows[j].get('tick_volume', 0) for j in range(max(0, idx - 100), idx + 1)]
    vm = sum(vols) / len(vols)
    vs = float(np.std(vols)) or 1.0
    vz = (rows[idx].get('tick_volume', 0) - vm) / vs
    hi = max(rows[j]['high'] for j in range(max(0, idx - 48), idx + 1))
    lo = min(rows[j]['low'] for j in range(max(0, idx - 48), idx + 1))
    pos = (rows[idx]['close'] - lo) / ((hi - lo) or 1e-9)
    slope = (rows[idx]['close'] - rows[max(0, idx - 48)]['close']) / (atr_now or 1e-9)
    style = str(sig.get('style') or sig.get('execution_style') or '')
    return [pct, vz, pos, slope,
            math.sin(t.hour / 24 * 2 * math.pi), math.cos(t.hour / 24 * 2 * math.pi),
            GRADE_NUM.get(sig.get('grade'), 0),
            1.0 if 'discount' in style else 0.0,
            1.0 if 'premium' in style else 0.0,
            1.0 if str(sig.get('side')) == 'BUY' else 0.0]


def train_lr(X, y, l2=1.0, iters=600, lr=0.2):
    mu, sd = X.mean(0), (X.std(0) + 1e-9)
    Z = np.c_[(X - mu) / sd, np.ones(len(X))]
    w = np.zeros(Z.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Z @ w))
        g = Z.T @ (p - y) / len(y) + l2 * np.r_[w[:-1], 0.0] / len(y)
        w -= lr * g
    return mu, sd, w


def predict(model, X):
    mu, sd, w = model
    Z = np.c_[(X - mu) / sd, np.ones(len(X))]
    return 1 / (1 + np.exp(-Z @ w))


# ── monkeypatch hook: wrap strategy_signal with the active filters ──
_ORIG_SS = br.strategy_signal
_TIME2IDX = {}


def _wrapped(row, h1w, h4w, bar_index, m15_window=None, range_kill_conf=0.35):
    global SEG
    if KILLZONE:
        h = datetime.fromtimestamp(row['time'], tz=timezone.utc).hour
        if not (7 <= h < 10 or 13 <= h < 16):
            return None
    sig = _ORIG_SS(row, h1w, h4w, bar_index, m15_window=m15_window,
                   range_kill_conf=range_kill_conf)
    if sig is None:
        return None
    idx = _TIME2IDX.get(row['time'], bar_index)
    if ATRBAND:
        pct = features(SEG, idx, sig)[0]
        if pct < 0.10 or pct > 0.90:
            return None
    if META is not None and META_THRESH is not None:
        f = np.array([features(SEG, idx, sig)])
        if float(predict(META, f)[0]) < META_THRESH:
            return None
    return sig


def run_segment(bridge, seg_rows):
    global SEG, _TIME2IDX
    SEG = seg_rows
    _TIME2IDX = {r['time']: i for i, r in enumerate(seg_rows)}
    data = dict(DATA)
    data['M5'] = seg_rows
    return br.run_backtest(bridge, symbol='XAUUSD', timeframe='M5', data=data,
                           spread_override=0.20, min_rr=1.5, min_grade='B',
                           partial_tp1_share=0.7,
                           partial_share_fn=_partial_close_fraction)


def summarize(res):
    t = res.get('trade_log', [])
    pnls = [x['pnl'] for x in t]
    eq = peak = dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    dec = [x for x in t if abs(x['pnl']) > 1e-9]
    wr = sum(1 for x in dec if x['pnl'] > 0) / len(dec) if dec else 0
    return {'n': len(t), 'wr_decided': round(wr, 3), 'net': round(sum(pnls), 2),
            'maxdd': round(dd, 2), 'worst': round(min(pnls), 2) if pnls else 0}


def main():
    # b52: was os.getenv('BRIDGE_TOKEN') — a name that exists in NO .env/unit/
    # crontab (the harvested-probe bug class); BridgeClient's own fallback
    # masked it, but the read was dead. Use the real key.
    bridge = BridgeClient(token=os.getenv('HERMES_BRIDGE_TOKEN'))
    br.strategy_signal = _wrapped          # arm hook (run_backtest resolves global)

    train_rows = ROWS[:SPLIT]
    test_rows = ROWS[SPLIT - PAD:]

    # train arm: baseline on train segment -> trades -> meta model
    train_res = run_segment(bridge, train_rows)
    tr = summarize(train_res)
    trades = train_res.get('trade_log', [])
    X = np.array([features(train_rows, t['entry_index'], t) for t in trades])
    y = np.array([1.0 if t['pnl'] > 0 else 0.0 for t in trades])
    global META
    META = train_lr(X, y) if len(trades) >= 40 else None
    sep = float(predict(META, X)[y == 1].mean() - predict(META, X)[y == 0].mean()) if META else -1
    print(f'train: {tr} | meta sep={sep:.3f}', flush=True)

    results = {'split_bar': SPLIT, 'train': tr, 'train_trades': len(trades),
               'meta_separation': round(sep, 3)}
    results['test_baseline'] = summarize(run_segment(bridge, test_rows))
    if META:
        for th in (0.35, 0.45, 0.55):
            globals()['META_THRESH'] = th
            results[f'test_meta_{th}'] = summarize(run_segment(bridge, test_rows))
        globals()['META_THRESH'] = None
    globals()['KILLZONE'] = True
    results['test_killzone'] = summarize(run_segment(bridge, test_rows))
    globals()['KILLZONE'] = False
    globals()['ATRBAND'] = True
    results['test_atr_band'] = summarize(run_segment(bridge, test_rows))
    globals()['ATRBAND'] = False
    OUT.write_text(json.dumps(results, indent=1))
    print(json.dumps(results, indent=1), flush=True)


if __name__ == '__main__':
    main()
