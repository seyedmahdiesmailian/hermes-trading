"""Which of the dormant ICT/RTM concepts actually predict anything?

breaker_blocks, rejection_blocks, power_of_three, turtle_soup,
volume_imbalance, silver_bullet, session_liquidity are all IMPLEMENTED but
NEVER WIRED into smc_analyse — the only callers live in legacy_removed/ and
archive/. Before wiring any of them in, measure whether the signal predicts
the next-bar direction. A concept that doesn't predict is not a feature, it
is code that costs money to maintain.

Method: on 2000 real M5 bars, evaluate each detector on every bar and check
whether its direction call predicts the sign of the next N bars' net move.
Report hit rate + sample size. A sample below ~100 is not evidence.
"""
import sys, collections
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import fetch_all_ohlc
from engines.smc import (detect_breaker_blocks, detect_rejection_blocks,
                         detect_power_of_three, detect_turtle_soup,
                         detect_volume_imbalance)

bc = BridgeClient()
bars = fetch_all_ohlc(bc, symbol='XAUUSD', timeframe='M5', count=2500)
print(f"loaded {len(bars)} M5 bars\n")

def ahead(i, k):
    """sign of the net move over the next k bars after index i"""
    if i + k >= len(bars):
        return None
    c0 = float(bars[i]['close']); c1 = float(bars[i + k]['close'])
    return 1 if c1 > c0 else (-1 if c1 < c0 else 0)

DETECTORS = [
    ('breaker_blocks', lambda w: [(b['type'], 1 if 'bullish' in b['type'] else -1)
                                  for b in detect_breaker_blocks(w)]),
    ('rejection_blocks', lambda w: [(b['type'], 1 if 'bullish' in b['type'] else -1)
                                    for b in detect_rejection_blocks(w)]),
    ('power_of_three', lambda w: [('distribution' if detect_power_of_three(w)['phase'] == 'distribution'
                                   else 'accumulation' if detect_power_of_three(w)['phase'] == 'accumulation'
                                   else None,
                                   1 if detect_power_of_three(w)['phase'] == 'distribution'
                                   else -1 if detect_power_of_three(w)['phase'] == 'accumulation' else 0)]),
    ('turtle_soup', lambda w: [(detect_turtle_soup(w)['type'],
                                1 if detect_turtle_soup(w)['type'] == 'bullish'
                                else -1 if detect_turtle_soup(w)['type'] == 'bearish' else 0)]),
    ('volume_imbalance', lambda w: [(b['type'], 1 if b['type'] == 'bullish' else -1)
                                    for b in detect_volume_imbalance(w)]),
]

HORIZONS = [2, 6, 12]
print(f"{'detector':<19}" + "".join(f"{'h=' + str(h):>12}" for h in HORIZONS))
print("-" * 60)

for name, fn in DETECTORS:
    cells = []
    for h in HORIZONS:
        hits = 0; n = 0
        for i in range(50, len(bars) - h):
            window = bars[max(0, i - 60):i + 1]
            try:
                sigs = fn(window)
            except Exception:
                continue
            if not sigs:
                continue
            # use the last signal
            _, direction = sigs[-1]
            if direction == 0:
                continue
            d = ahead(i, h)
            if d is None or d == 0:
                continue
            n += 1
            if d == direction:
                hits += 1
        cells.append(f"{hits/max(1,n)*100:>5.0f}% n={n:<6}" if n else "     -      ")
    print(f"{name:<19}" + "".join(f"{c:>12}" for c in cells))
