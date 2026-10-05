"""b239 part 5 — the real fix: a discount-only entry condition.

The live trades entered at 4151.67 / 4154.10 near the TOP of a long zone
whose ceiling was 4155.77 — and tp_levels[0] was that same ceiling. b238's
reanchor fixes the SL/TP geometry (0.05R -> 1.55R), but it treats the
symptom. The deeper question: should the in-zone entry fire AT ALL when
price sits in the top of the zone?

ICT doctrine: trade only from discount (bottom half of the zone) for longs.
The current code has no location condition — any bar inside the zone with a
trigger fires.

A/B on the live-parity funnel:
  BASE = HEAD (b238 reanchor present)
  FIX  = HEAD + require price in the discount half of the zone
Both legs run identical data; measure net PnL, trades, and the worst
realised RR in the ledger. A guard that blocks bad trades also blocks
trades, so the honest question is whether the kept trades are better.
"""
import sys, json
sys.path.insert(0, '.'); sys.path.insert(0, 'engines')
from env_loader import load_dotenv
load_dotenv('.env')
from bridge_client import BridgeClient
from engines.backtest_real import run_backtest
from engines import orchestrator as O
from engines import plan as P

bc = BridgeClient()

# ── probe: where do in-zone entries actually happen? ──
r = run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=3000, min_rr=1.5)
lo = [t for t in r['trade_log'] if t.get('style') == 'pullback_continuation']
hi = [t for t in r['trade_log'] if t.get('style') not in (None, '', 'pullback_continuation')]
print(f"pullback trades: {len(lo)} of {len(r['trade_log'])}")

# ── FIX leg: discount-only in-zone entry ──
_orig = P._buy_logic

def _buy_discount_only(plan, price, trigger_ok, now, m5_ok=True):
    z = plan['zones']
    if z['long_entry_low'] <= price <= z['long_entry_high']:
        mid = 0.5 * (z['long_entry_low'] + z['long_entry_high'])
        if price > mid:
            return {'action': 'wait_in_zone', 'reason': 'above_zone_midpoint',
                    'zone': 'long_zone', 'execution_style': 'pullback_wait',
                    'at': getattr(now, 'isoformat', lambda: str(now))()}
    return _orig(plan, price, trigger_ok, now, m5_ok)


def run_leg(discount_guard):
    P._buy_logic = _buy_discount_only if discount_guard else _orig
    try:
        return run_backtest(bc, symbol='XAUUSD', timeframe='M5', count=3000, min_rr=1.5)
    finally:
        P._buy_logic = _orig


base = run_leg(False)
fix = run_leg(True)

# canary: confirm the guard actually binds
n_wait = sum(1 for t in fix['trade_log'] if t.get('style') == 'pullback_wait')
print(f"\ncanary: base pullback trades={len([t for t in base['trade_log'] if t.get('style')=='pullback_continuation'])}"
      f"  fix pullback trades={len([t for t in fix['trade_log'] if t.get('style')=='pullback_continuation'])}")

for label, res in (('BASE (head)', base), ('FIX (discount-only)', fix)):
    tl = res['trade_log']
    net = sum(float(t.get('pnl') or 0) for t in tl)
    wins = sum(1 for t in tl if float(t.get('pnl') or 0) > 0)
    rrs = []
    for t in tl:
        ent, sl = float(t['entry']), float(t.get('orig_sl') or 0)
        tp = float(t.get('exit') or 0)
        if sl and tp and abs(ent - sl) > 0:
            rrs.append(abs(tp - ent) / abs(ent - sl))
    worst = min(rrs) if rrs else 0
    print(f"\n{label}\n  trades={len(tl)}  wins={wins}  WR={100*wins/max(1,len(tl)):.1f}%"
          f"  net={net:+.2f}  worstR={worst:.2f}  meanR={sum(rrs)/max(1,len(rrs)):.2f}")

json.dump({'base': {'trades': len(base['trade_log']), 'net': round(sum(float(t.get('pnl') or 0) for t in base['trade_log']), 2)},
           'fix': {'trades': len(fix['trade_log']), 'net': round(sum(float(t.get('pnl') or 0) for t in fix['trade_log']), 2)}},
          open('data/backtest/b239_discount_guard.json', 'w'), indent=1)
