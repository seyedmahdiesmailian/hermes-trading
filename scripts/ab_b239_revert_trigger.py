"""b239 part 10 — the trigger is confirming the WRONG thing.

m5_confirmation for a BUY requires 3 consecutive RISING closes. But when
regime == 'range' the plan is entry_mode 'mean_reversion_wait' — it buys
the bottom of the zone to sell the top. A rising-3 trigger means price has
ALREADY risen into the zone, i.e. it confirms the move that is about to be
reverted. That is the exact opposite of what a mean-reversion entry wants
to confirm.

Part 8 measured the cost: trigger fires -> +0.293 ATR forward in the
trade's direction; trigger absent -> +0.567 ATR, ~2x better.

A/B three legs on identical data:
  BASE   = HEAD (momentum confirmation)
  REVERT = confirmation INVERTED for mean-reversion plans (3 falling closes
           to buy the dip, 3 rising closes to sell the rip) — the signal a
           mean-reversion trader actually waits for
  NONE   = no confirmation at all

Guard rails identical across legs. If REVERT wins, the fix is not "less
confirmation" but "confirm the right thing".
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest
from engines import orchestrator as O

bc = BridgeClient()
_orig = O.m5_confirmation


def _revert_confirmation(rows, bias):
    """mirror of m5_confirmation: confirm the REVERSAL, not the trend"""
    closes = O._closes(rows, O.M5_CONFIRM_CLOSES)
    if not closes:
        return False
    if bias == 'bullish':
        return all(closes[i] > closes[i + 1] for i in range(len(closes) - 1))
    if bias == 'bearish':
        return all(closes[i] < closes[i + 1] for i in range(len(closes) - 1))
    return False


def run_leg(mode):
    if mode == 'base':
        O.m5_confirmation = _orig
    elif mode == 'revert':
        O.m5_confirmation = _revert_confirmation
    else:
        O.m5_confirmation = lambda rows, bias: True
    try:
        return run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=3000, min_rr=1.5)
    finally:
        O.m5_confirmation = _orig


def summary(label, res):
    tl = res['trade_log']
    net = sum(float(t.get('pnl') or 0) for t in tl)
    wins = sum(1 for t in tl if float(t.get('pnl') or 0) > 0)
    print(f"\n{label}\n  trades={len(tl)}  WR={100*wins/max(1,len(tl)):.1f}%  net={net:+.2f}")
    return {'trades': len(tl), 'net': round(net, 2), 'wr': round(100*wins/max(1,len(tl)), 1)}


out = {}
for mode, label in (('base', 'BASE (momentum trigger)'),
                    ('revert', 'REVERT (reversal trigger)'),
                    ('none', 'NONE')):
    out[mode] = summary(label, run_leg(mode))

print(f"\nrevert vs base: net {out['revert']['net']-out['base']['net']:+.2f}  "
      f"trades {out['revert']['trades']-out['base']['trades']:+d}")
print(f"none  vs base: net {out['none']['net']-out['base']['net']:+.2f}  "
      f"trades {out['none']['trades']-out['base']['trades']:+d}")
json.dump(out, open('data/backtest/b239_revert_trigger.json', 'w'), indent=1)
print('\nsaved data/backtest/b239_revert_trigger.json')
