#!/usr/bin/env python3
"""Reusable A/B harness for the live-parity funnel.

Pattern (established by ab_aggressive_entry / ab_range_kill / ab_zone_width):
  one cached M5 robustness dataset → run_backtest(data=...) per variant,
  patching engine constants in-process (never on disk).

Usage:
  python3 scripts/ab.py <name> <module:CONST=v1,v2,v3> [more module:CONST=...]

Examples:
  python3 scripts/ab.py be_at_r engines.trade_management:BREAKEVEN_AT_R=0.4,0.5,0.6
  python3 scripts/ab.py zone engines.context:ZONE_LOOKBACK=8,12,20

Prints per-variant: profitable windows / trades / PnL / avg WR, then a
verdict line (best by PnL, best by PnL-per-trade). Read-only w.r.t. live:
touches no state files, no plan, no bridge orders (bridge used for health only).
"""
import importlib
import json
import os
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

from bridge_client import BridgeClient
from engines.backtest_real import run_backtest

DATA_PATH = Path(_ROOT) / 'data/backtest/robustness_data_M5.json'
WINDOW = 500


def _cast(v: str):
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def parse_spec(spec: str):
    """'module:CONST=1,2,3' → (module, const, [1,2,3]) with smart casting.
    Special module 'backtest' → kwarg of run_backtest (e.g. backtest:breakeven_at_r=...)."""
    mod_name, rest = spec.split(':', 1)
    const, vals = rest.split('=', 1)
    parsed = [_cast(v) for v in vals.split(',')]
    if mod_name == 'backtest':
        return None, const, parsed          # kwarg mode
    return importlib.import_module(mod_name), const, parsed


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    name = sys.argv[1]
    specs = [parse_spec(s) for s in sys.argv[2:]]

    data = json.loads(DATA_PATH.read_text())
    base = {k: v for k, v in data.items()}
    entry_tf = 'M5' if 'M5' in data else 'M15'
    bars = data[entry_tf]
    n_windows = min(13, len(bars) // WINDOW)
    bridge = BridgeClient()

    print(f"A/B '{name}' on {n_windows} cached {entry_tf} windows ({WINDOW} bars each)")
    results = []
    for mod, const, values in specs:
        original = None if mod is None else getattr(mod, const)
        for val in values:
            extra_kwargs = {}
            if mod is None:
                extra_kwargs[const] = val          # run_backtest kwarg
            else:
                setattr(mod, const, val)
            tot_pnl = tot_tr = 0.0
            prof = 0
            wrs = []
            for w in range(n_windows):
                lo, hi = w * WINDOW, (w + 1) * WINDOW
                slice_data = {entry_tf: bars[lo:hi], "H1": data["H1"], "H4": data["H4"]}
                r = run_backtest(bridge, symbol="XAUUSD", timeframe=entry_tf,
                                 count=WINDOW, data=slice_data, **extra_kwargs)
                if not r or not r.get("ok"):
                    continue
                pnl = float(r.get("net_pnl", 0))
                tot_pnl += pnl
                tot_tr += r.get("trades", 0)
                prof += 1 if pnl > 0 else 0
                wrs.append(float(r.get("win_rate", 0)))
            per_tr = tot_pnl / tot_tr if tot_tr else 0
            label = f"backtest:{const}" if mod is None else f"{mod.__name__}.{const}"
            print(f"  {label}={val!r:>8}: "
                  f"prof={int(prof)}/{n_windows} trades={tot_tr:.0f} "
                  f"pnl={tot_pnl:+.2f} pnl/trade={per_tr:+.2f} "
                  f"avgWR={100*sum(wrs)/max(1,len(wrs)):.1f}%")
            results.append((f"{const}={val!r}", tot_pnl, per_tr, int(prof)))
        if mod is not None:
            setattr(mod, const, original)  # restore — never leave patched state

    best_pnl = max(results, key=lambda x: x[1])
    best_eff = max(results, key=lambda x: x[2])
    print(f"VERDICT: best PnL → {best_pnl[0]} ({best_pnl[1]:+.2f}); "
          f"best per-trade → {best_eff[0]} ({best_eff[2]:+.2f})")


if __name__ == '__main__':
    main()
