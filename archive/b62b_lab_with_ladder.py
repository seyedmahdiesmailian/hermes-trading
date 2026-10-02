#!/usr/bin/env python3
"""b62 follow-up: run the 3 profitable classic arms WITH the live b60 exit
ladder (same partial_share_fn + trail + tp1 placement as b61's best arm),
so entry quality is compared on identical exit geometry."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import importlib.util
spec = importlib.util.spec_from_file_location("lab", os.path.join(os.path.dirname(__file__), "b62_strategy_lab.py"))
lab = importlib.util.module_from_spec(spec)
# prevent main() from running: module guards it under __main__, safe
spec.loader.exec_module(lab)
from engines.backtest import backtest_ohlc
from engines.trade_management import _partial_close_fraction

ARMS = {"asia_break": lab.asia_breakout, "ema_pullback": lab.ema_pullback,
        "bb_bounce": lab.bollinger_bounce}
for name, fn in ARMS.items():
    res = backtest_ohlc(lab.M15, lab.indexed(fn), min_rr=0.0, spread=lab.SPREAD,
                        breakeven_at_r=0.0,
                        partial_share_fn=lambda t: _partial_close_fraction(t),
                        tp1_position=0.50, trail_after_partial=0.5)
    s = lab.r_stats(res); s["maxDD_R"] = lab.max_dd(res)
    print(f"{name:14s} +b60ladder -> {s}")
