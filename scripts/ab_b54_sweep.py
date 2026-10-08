#!/usr/bin/env python3
"""b54: full strategy-parameter sweep on the live-parity M5 funnel.

Every knob the entry/management funnel exposes, swept on ONE byte-identical
dataset (robustness_data_M5.json, 6500 bars ≈ 3 weeks):

  entry gates:   range_kill_conf (0.35 live), SMC confidence floor for
                 aggressive lanes (0.4 live, 4 call sites in plan.py)
  geometry:      _reanchor stop cap (2.0 ATR live), re-anchor min_rr (1.5),
                 ZONE_LOOKBACK (12 live)
  management:    partial TP1 share (0.5 live), partial TP1 position (0.5 live)

Monkeypatching module constants is how ab_zone_width already does it; the
SMC floor and reanchor knobs get real module-level constants first (this
script FAILS LOUDLY if they are missing — no silent no-op sweeps).

Read-only: never touches order endpoints. Output: ab_b54_sweep_results.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from env_loader import load_dotenv
load_dotenv(ROOT / '.env')

from bridge_client import BridgeClient
from engines import plan as plan_mod
from engines import context as ctx_mod
from engines.backtest_real import run_backtest

DATA = json.loads((ROOT / 'data/backtest/robustness_data_M5.json').read_text())
OUT = ROOT / 'data/backtest/ab_b54_sweep_results.json'

# ── fail-loud: the knobs must exist as patchable module constants ──
assert hasattr(plan_mod, 'SMC_CONF_FLOOR'), 'plan.py must expose SMC_CONF_FLOOR (b54)'
assert hasattr(plan_mod, 'REANCHOR_STOP_ATR_CAP'), 'plan.py must expose REANCHOR_STOP_ATR_CAP (b54)'
assert hasattr(plan_mod, 'REANCHOR_MIN_RR'), 'plan.py must expose REANCHOR_MIN_RR (b54)'

_orig_smc = plan_mod.SMC_CONF_FLOOR
_orig_cap = plan_mod.REANCHOR_STOP_ATR_CAP
_orig_rr = plan_mod.REANCHOR_MIN_RR
_orig_lb = ctx_mod.ZONE_LOOKBACK


def set_knobs(smc=None, cap=None, rr=None, lookback=None):
    plan_mod.SMC_CONF_FLOOR = _orig_smc if smc is None else smc
    plan_mod.REANCHOR_STOP_ATR_CAP = _orig_cap if cap is None else cap
    plan_mod.REANCHOR_MIN_RR = _orig_rr if rr is None else rr
    ctx_mod.ZONE_LOOKBACK = _orig_lb if lookback is None else lookback


def summarize(res: dict) -> dict:
    t = res.get('trade_log', [])
    pnls = [x['pnl'] for x in t]
    eq = peak = dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    dec = res.get('wins', 0) + res.get('losses', 0)
    return {'n': len(t), 'W': res.get('wins', 0), 'L': res.get('losses', 0),
            'WR': round(res.get('wins', 0) / dec, 3) if dec else 0,
            'net': res.get('net_pnl', 0),
            'avg': round(sum(pnls) / len(pnls), 2) if pnls else 0,
            'maxdd': round(dd, 2), 'worst': round(min(pnls), 2) if pnls else 0}


CONFIGS = [
    # label,            backtest kwargs,                    knob overrides
    ("A_live_baseline",  {},                                 {}),
    # SMC confidence floor for aggressive lanes
    ("smc_0.30",         {},                                 {"smc": 0.30}),
    ("smc_0.50",         {},                                 {"smc": 0.50}),
    ("smc_0.60",         {},                                 {"smc": 0.60}),
    # re-anchor stop cap (ATR multiples)
    ("stopcap_1.5",      {},                                 {"cap": 1.5}),
    ("stopcap_2.5",      {},                                 {"cap": 2.5}),
    # re-anchor min RR (geometry quality of late entries)
    ("minrr_re_1.8",     {},                                 {"rr": 1.8}),
    ("minrr_re_2.2",     {},                                 {"rr": 2.2}),
    # zone lookback (M5 bars)
    ("zone_lb_8",        {},                                 {"lookback": 8}),
    ("zone_lb_20",       {},                                 {"lookback": 20}),
    # range-kill confidence
    ("rkill_0.20",       {"range_kill_conf": 0.20},          {}),
    ("rkill_0.50",       {"range_kill_conf": 0.50},          {}),
    # entry RR floor (executor gate 6)
    ("minrr_1.3",        {"min_rr": 1.3},                    {}),
    ("minrr_1.4",        {"min_rr": 1.4},                    {}),
    # TP ladder: partial share at TP1 and TP1 position
    ("part_0.3",         {"partial_tp1_share": 0.3},         {}),
    ("part_0.7",         {"partial_tp1_share": 0.7},         {}),
    ("tp1_0.65",         {"tp1_position": 0.65},             {}),
    ("tp1_0.35",         {"tp1_position": 0.35},             {}),
]


def main() -> None:
    bridge = BridgeClient()
    out = {}
    for label, kw, knobs in CONFIGS:
        set_knobs(**knobs)
        try:
            res = run_backtest(bridge, timeframe='M5', data=DATA, **kw)
            s = summarize(res)
            out[label] = {'kwargs': kw, 'knobs': knobs, **s}
            print(f"{label:16s} n={s['n']:3d} WR={s['WR']:5.1%} net={s['net']:+8.2f} "
                  f"avg={s['avg']:+6.2f} maxdd={s['maxdd']:6.2f} worst={s['worst']:+7.2f}",
                  flush=True)
        finally:
            set_knobs()  # always restore
    OUT.write_text(json.dumps(out, indent=2))
    print(f"saved -> {OUT}")


if __name__ == '__main__':
    main()
