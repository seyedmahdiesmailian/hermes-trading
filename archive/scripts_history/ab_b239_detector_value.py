"""b239 part 3 — do the orphan ICT detectors have real predictive value?

14 of 18 smc.py detectors compute fields the entry decision never reads:
liquidity_sweep, power_of_three, turtle_soup, silver_bullet, ote_zone,
volume_imbalance, breaker_blocks, rejection_blocks, session_liquidity...

Before wiring any of them in, test whether they PREDICT anything on real
data. A detector that fires constantly and doesn't move the next bars is
worse than absent — it adds false confidence.

Method: walk M5 history. At each bar, run the orphan detectors and record
their signal. Then measure forward drift (next 12 bars) conditioned on the
detector firing vs a matched baseline. A detector earns its place only if
its conditional drift beats the unconditional one.
"""
import sys, json, collections
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import fetch_all_ohlc
from engines.smc import (detect_liquidity_sweep, detect_power_of_three,
                         detect_turtle_soup, evaluate_silver_bullet_setup,
                         compute_session_liquidity, detect_volume_imbalance,
                         detect_breaker_blocks, compute_ote_zone,
                         market_structure_phase, premium_discount_zone)
from datetime import datetime, timezone

bc = BridgeClient()
rows = fetch_all_ohlc(bc, 'XAUUSD', 'M5', 3000)
print('M5 bars:', len(rows))

HORIZON = 12  # bars forward
ATR_WIN = 24

def drift(rows, i, n):
    """forward move in ATR units over the next n bars"""
    base = float(rows[i]['close'])
    fwd = rows[i + 1:i + 1 + n]
    if not fwd:
        return None
    end = float(fwd[-1]['close'])
    atr = sum(abs(float(r['high']) - float(r['low'])) for r in rows[i - ATR_WIN:i + 1]) / ATR_WIN
    if atr <= 0:
        return None
    return (end - base) / atr

results = {}
n = len(rows)

for name, fn, kind in [
    ('liquidity_sweep', detect_liquidity_sweep, 'tuple'),
    ('power_of_three', detect_power_of_three, 'dict'),
    ('turtle_soup', detect_turtle_soup, 'dict'),
    ('volume_imbalance', detect_volume_imbalance, 'list'),
    ('breaker_blocks', detect_breaker_blocks, 'list'),
    ('session_liquidity', compute_session_liquidity, 'dict'),
]:
    fires, drifts_on, drifts_off = 0, [], []
    for i in range(ATR_WIN, n - HORIZON - 1):
        win = rows[i - 60:i + 1]
        try:
            r = fn(win) if name != 'session_liquidity' else fn(win, 'asia')
        except Exception:
            continue
        hit = False
        if kind == 'tuple':
            hit = bool(r and r[0])
        elif kind == 'dict':
            hit = bool(r and r.get('detected') or r.get('phase') or r.get('sweep'))
        elif kind == 'list':
            hit = bool(r)
        d = drift(rows, i, HORIZON)
        if d is None:
            continue
        if hit:
            fires += 1
            drifts_on.append(d)
        else:
            drifts_off.append(d)
    if drifts_on and drifts_off:
        mon = sum(drifts_on) / len(drifts_on)
        moff = sum(drifts_off) / len(drifts_off)
        results[name] = {'fires': fires, 'rate': round(fires / (len(drifts_on) + len(drifts_off)), 3),
                         'drift_when_on': round(mon, 4), 'drift_when_off': round(moff, 4),
                         'separation': round(mon - moff, 4)}
        print(f"  {name:20s} fires={fires:5d} ({results[name]['rate']*100:5.1f}%)  "
              f"drift_on={mon:+.4f} drift_off={moff:+.4f}  sep={mon-moff:+.4f} ATR")

json.dump(results, open('data/backtest/b239_detector_value.json', 'w'), indent=1)
print('\nsaved data/backtest/b239_detector_value.json')
