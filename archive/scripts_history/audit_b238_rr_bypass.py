"""Why did the two live trades take a 0.14R trade?

Reconstructed from the live plan at 06:20 UTC Oct 5 (plan xau-cc1480bb):
    entry        4151.81  (live fill, BUY in the long zone)
    sl           4123.59  (plan invalidation — the STRUCTURAL stop)
    tp1          4155.77  (tp_levels[0])
    -> risk $28.22 to make $3.96 = 0.14R

The RR gate should have refused it. Three reasons it did not:

  1. sl = plan['invalidation']. The structural stop is a whole-zone
     invalidation, so its distance from entry is whatever the zone happens
     to be — not a risk the trade takes.
  2. tp = tp_levels[0]. The first target is the zone boundary, which sits
     ~$4 away.
  3. execution_style = 'pullback_continuation', which is in
     RR_FLOOR_EXEMPT_STYLES. The floor is bypassed entirely.

The b233d study that justified the exemption measured it on CHASE styles
(aggressive_value_entry, pullback_continuation). This trade is not a chase —
it is an in-zone pullback entry with a structural stop, which is exactly the
setup the floor exists to protect. The exemption is too broad.

This audit reproduces the trade and measures what the gate would have done
if the floor applied. We do NOT guess a fix: we measure how many
pullback_continuation entries would have been refused, and what their real
outcome was, over the live-parity backtest.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

bc = BridgeClient()

# reproduce the live geometry from the actual plan
ENTRY, SL, TP1 = 4151.81, 4123.59, 4155.77
risk = abs(ENTRY - SL)
reward = abs(TP1 - ENTRY)
print(f"live trade: entry {ENTRY}  sl {SL}  tp1 {TP1}")
print(f"  risk ${risk:.2f}  reward ${reward:.2f}  RR = {reward/risk:.2f}")
print(f"  at MIN_RISK_REWARD=2.0 this needs reward ${risk*2:.2f}, not ${reward:.2f}")
print(f"  -> a 0.14R trade risking $28 to make $4. Lot 0.01 = $2.81 of risk\n")

# how many pullback_continuation entries does the lab actually see, and
# what happens if the floor applies to them?
print("=== backtest: the floor's effect on pullback entries ===")
t = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=5000,
                 min_rr=1.5)['trade_log']
pc = [x for x in t if x.get('execution_style') == 'pullback_continuation']
print(f"  total trades {len(t)}, pullback_continuation {len(pc)}")
if pc:
    won = sum(1 for x in pc if float(x['pnl']) > 0)
    tot = sum(float(x['pnl']) for x in pc)
    print(f"  pullback: {won}/{len(pc)} won, net {tot:+.2f}")
    rrs = []
    for x in pc:
        r = float(x.get('risk_price') or 0)
        ew = float(x.get('entry_price') or 0)
        tp = float(x.get('tp_price') or 0)
        if r and ew:
            rrs.append(abs(tp - ew) / r)
    if rrs:
        print(f"  mean RR {sum(rrs)/len(rrs):.2f}, min {min(rrs):.2f}")
