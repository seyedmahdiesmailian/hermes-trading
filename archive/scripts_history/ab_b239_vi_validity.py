"""b239 part 6 — is the volume_imbalance edge real or a mirage?

Part 3 measured: when volume_imbalance fires, forward drift is -1.01 ATR
over 12 bars vs -0.013 when it does not. Separation -0.99 ATR. That is a
huge effect — large enough to be suspicious.

Two failure modes to rule out before trusting it:
 1. LOOKAHEAD: the detector may read bars at or after the decision bar.
 2. NON-STATIONARITY: the edge may live in one slice of history (e.g. the
    steep trend window) and be absent in others — a regime artifact.

Test 1: shift the window so the detector sees only bars < i, and re-measure
the drift from bar i. If separation collapses, it was lookahead.
Test 2: split the history into four equal quarters and measure separation
in each. A real edge persists; a regime artifact concentrates in one.

Only if both pass is this worth wiring into the entry decision.
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
print('M5 bars:', n)

ATR, HZN = 24, 12


def drift(i, n=HZN):
    base = float(rows[i]['close'])
    fwd = rows[i + 1:i + 1 + n]
    if not fwd:
        return None
    atr = sum(abs(float(r['high']) - float(r['low'])) for r in rows[i - ATR:i + 1]) / ATR
    return (float(fwd[-1]['close']) - base) / atr if atr > 0 else None


# ── TEST 1: strictly causal window (detector sees only bars <= i) ──
print('\n=== TEST 1: strictly causal window ===')
on, off = [], []
for i in range(ATR, n - HZN - 1):
    win = rows[max(0, i - 60):i + 1]          # ends AT i, no future bars
    try:
        hit = bool(detect_volume_imbalance(win))
    except Exception:
        continue
    d = drift(i)
    if d is None:
        continue
    (on if hit else off).append(d)
if on and off:
    sep_causal = sum(on) / len(on) - sum(off) / len(off)
    print(f"  on n={len(on)}  mean={sum(on)/len(on):+.4f}")
    print(f"  off n={len(off)}  mean={sum(off)/len(off):+.4f}")
    print(f"  CAUSAL separation = {sep_causal:+.4f} ATR")
else:
    print('  no hits')
    sep_causal = None

# ── TEST 2: stability across four quarters of history ──
print('\n=== TEST 2: separation by quarter ===')
q = n // 4
per = []
for k in range(4):
    onq, offq = [], []
    for i in range(k * q + ATR, min((k + 1) * q, n - HZN - 1)):
        win = rows[max(0, i - 60):i + 1]
        try:
            hit = bool(detect_volume_imbalance(win))
        except Exception:
            continue
        d = drift(i)
        if d is None:
            continue
        (onq if hit else offq).append(d)
    if onq and offq:
        s = sum(onq) / len(onq) - sum(offq) / len(offq)
        per.append(s)
        print(f"  Q{k+1}: on n={len(onq):4d} off n={len(offq):4d}  sep={s:+.4f} ATR")
    else:
        print(f"  Q{k+1}: no hits")

json.dump({'causal_sep': round(sep_causal or 0, 4),
           'quarters': [round(x, 4) for x in per]},
          open('data/backtest/b239_vi_validity.json', 'w'), indent=1)
print('\nsaved data/backtest/b239_vi_validity.json')
