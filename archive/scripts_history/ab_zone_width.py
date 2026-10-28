#!/usr/bin/env python3
"""A/B zone lookback (8/12/20 bars) on the cached M5 robustness dataset.

compute_m5_zones uses the last N bars for the entry-zone mid. Wider = zones
lag fast moves; tighter = zones chase noise. Measure PnL+trades per setting
through the live-parity funnel (run_backtest), same pattern as ab_range_kill.
"""
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
from engines import context as ctx_mod
from engines.backtest_real import run_backtest

DATA = json.loads((Path(_ROOT) / 'data/backtest/robustness_data_M5.json').read_text())
WINDOW = 500
m15, h1, h4 = DATA["M5"], DATA["H1"], DATA["H4"]
n_windows = min(13, len(m15) // WINDOW)
bridge = BridgeClient()

for look in (8, 12, 20):
    ctx_mod.ZONE_LOOKBACK = look
    tot_pnl = tot_tr = prof = 0.0
    wrs = []
    for w in range(n_windows):
        lo, hi = w * WINDOW, (w + 1) * WINDOW
        slice_data = {"M5": m15[lo:hi], "H1": h1, "H4": h4}
        r = run_backtest(bridge, symbol="XAUUSD", timeframe="M5",
                         count=WINDOW, data=slice_data)
        if not r or not r.get("ok"):
            continue
        pnl = r.get("net_pnl", 0)
        tot_pnl += pnl
        tot_tr += r.get("trades", 0)
        prof += 1 if pnl > 0 else 0
        wrs.append(r.get("win_rate", 0))
    print(f"lookback={look:2d}: windows={n_windows} profitable={prof} "
          f"trades={tot_tr:.0f} pnl={tot_pnl:+.2f} avgWR={sum(wrs)/max(1,len(wrs)):.1f}")
