"""b239 part 7 — can the volume_imbalance edge actually make money?

Validated (part 6): strictly causal, separation -0.99 ATR, stable across
all four quarters of history. The edge is real as a DIRECTIONAL FORECAST.

But a forecast is not a trade. The entry still needs a stop and a target.
This prices it as a standalone rule:
  ENTRY: when volume_imbalance fires, go the direction it implies (down)
  STOP:  entry + k*ATR (k = 1.0, 1.5, 2.0, 2.5, 3.0)
  TP:    entry - R*k*ATR (R = 1.0, 1.5, 2.0)
and reports net R per trade. Compare against the funnel's incumbent
(1.03-1.18 realised R). Only if a (k, R) arm clears ~1.5R with decent
frequency is it worth promoting into plan.py.
"""
import sys, json, collections
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import fetch_all_ohlc
from engines.smc import detect_volume_imbalance

bc = BridgeClient()
rows = fetch_all_ohlc(bc, 'XAUUSD', 'M5', 3000)
n = len(rows)
ATR = 24
print('M5 bars:', n)


def atr_at(i):
    seg = rows[i - ATR:i + 1]
    return sum(abs(float(r['high']) - float(r['low'])) for r in seg) / len(seg)


# ── the detector's implied direction ──
print('\n=== signal direction check (part 3 showed negative drift) ===')
dirs = collections.Counter()
for i in range(ATR, n - 1):
    win = rows[max(0, i - 60):i + 1]
    try:
        r = detect_volume_imbalance(win)
    except Exception:
        continue
    if r:
        last = r[-1] if isinstance(r, list) else r
        d = last.get('direction') if isinstance(last, dict) else None
        dirs[d or 'unlabelled'] += 1
print('  direction labels:', dict(dirs))

# ── price it as a SHORT rule (drift is down) ──
print('\n=== priced as short rule ===')
arms = {}
for k in (1.0, 1.5, 2.0, 2.5, 3.0):
    for R in (1.0, 1.5, 2.0):
        trades = []
        for i in range(ATR, n - 40):
            win = rows[max(0, i - 60):i + 1]
            try:
                hit = bool(detect_volume_imbalance(win))
            except Exception:
                continue
            if not hit:
                continue
            a = atr_at(i)
            if a <= 0:
                continue
            entry = float(rows[i]['close'])
            sl = entry + k * a
            tp = entry - R * k * a
            # walk forward, exit on first touch (conservative: wick counts)
            out, reason = None, None
            for j in range(i + 1, min(i + 40, n)):
                hi, lo = float(rows[j]['high']), float(rows[j]['low'])
                if lo <= tp:
                    out, reason = tp, 'tp'
                    break
                if hi >= sl:
                    out, reason = sl, 'sl'
                    break
            if out is None:
                continue
            trades.append((R if reason == 'tp' else -1.0, reason))
        if trades:
            net = sum(t[0] for t in trades) / len(trades)
            wr = 100 * sum(1 for t in trades if t[1] == 'tp') / len(trades)
            arms[(k, R)] = {'n': len(trades), 'netR': round(net, 3), 'wr': round(wr, 1)}
            print(f"  k={k:<4} R={R:<4} n={len(trades):4d}  WR={wr:5.1f}%  netR={net:+.3f}")

best = max(arms.items(), key=lambda kv: kv[1]['netR']) if arms else None
print(f"\n  BEST arm: k={best[0][0]} R={best[0][1]} -> {best[1]}") if best else None
json.dump({f"k{k}_R{R}": v for (k, R), v in arms.items()},
          open('data/backtest/b239_vi_priced.json', 'w'), indent=1)
print('\nsaved data/backtest/b239_vi_priced.json')
