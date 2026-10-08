#!/usr/bin/env python3
"""b68d CONFIRM — htf_pullback vs the CURRENT live funnel on FRESH data.

b68 merit bar: an arm must beat the funnel on BOTH the cached 3000-bar set
AND one fresh fetch, same engine, same live b60 ladder. Cached result:
htf_pull_50 ladder +0.271R (n=74), htf_pull_618 +0.194R (n=68) vs funnel
+0.854R -> already short on cached. Per the b68 round-1 METHOD RULE the
funnel is RE-MEASURED on the SAME fresh bars so the arm settles honestly on
both numbers.
"""
import sys, os, json
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))   # b65: a BridgeClient consumer owns its env
from bridge_client import BridgeClient
from engines.backtest import backtest_ohlc
from engines.backtest_real import fetch_all_ohlc, strategy_signal
from engines.trade_management import _partial_close_fraction
from scripts import b68_htf_lab as lab
from scripts.b68_htf_lab import htf_pullback

TF = "M15"
COUNT = 6000
SPREAD = 0.20
LADDER = dict(partial_share_fn=lambda t: _partial_close_fraction(t),
              trail_after_partial=0.5, tp1_position=0.50,
              partial_tp1_share=0.5, breakeven_at_r=0.0)


def r_stats(res):
    rs = []
    for t in res.get("trade_log", []):
        risk = abs(float(t["entry"]) - float(t.get("orig_sl") or t["sl"])) or 1
        rs.append(float(t["pnl"]) / risk)
    if not rs:
        return {"n": 0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = abs(sum(losses) / len(losses)) if losses else 0.001
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {"n": len(rs), "wr": round(100 * len(wins) / len(rs), 1),
            "payoff": round(avg_w / avg_l, 2),
            "exp_R": round(sum(rs) / len(rs), 3),
            "tot_R": round(sum(rs), 1), "dd_R": round(-dd, 1)}


def main():
    bridge = BridgeClient()
    m15 = fetch_all_ohlc(bridge, "XAUUSD", TF, COUNT)
    h1 = fetch_all_ohlc(bridge, "XAUUSD", "H1", COUNT)
    h4 = fetch_all_ohlc(bridge, "XAUUSD", "H4", COUNT)
    print("bars:", len(m15), len(h1), len(h4), flush=True)
    idx_of = {r["time"]: n for n, r in enumerate(m15)}
    # htf_pullback closes over the MODULE-level M15/H1/IDX — repoint
    lab.M15 = m15
    lab.H1 = h1
    lab.IDX = idx_of

    def wrap(fn):
        def w(row):
            i = idx_of.get(row.get("time"))
            return None if i is None else fn(i)
        return w

    def funnel(row):
        i = idx_of.get(row.get("time"))
        if i is None:
            return None
        bt = row.get("time", 0)
        hw = [r for r in h1 if r.get("time", 0) <= bt][-80:]
        h4w = [r for r in h4 if r.get("time", 0) <= bt][-80:]
        mw = m15[max(0, i - 120):i + 1]
        return strategy_signal(row, hw, h4w, i, m15_window=mw)

    arms = [("CURRENT_FUNNEL", funnel),
            ("htf_pull_50", wrap(lambda i: htf_pullback(i, 0.50))),
            ("htf_pull_618", wrap(lambda i: htf_pullback(i, 0.618)))]
    out = {}
    print(f"{'arm':18s} {'n':>4s} {'WR%':>6s} {'payoff':>7s} {'exp_R':>7s} "
          f"{'tot_R':>7s} {'dd_R':>6s}")
    for name, fn in arms:
        res = backtest_ohlc(m15, fn, min_rr=0.0, spread=SPREAD, **LADDER)
        s = r_stats(res)
        out[name] = s
        print(f"{name:18s} {s.get('n',0):4d} {s.get('wr',0):6.1f} "
              f"{s.get('payoff',0):7.2f} {s.get('exp_R',0):7.3f} "
              f"{s.get('tot_R',0):7.1f} {s.get('dd_R',0):6.1f}", flush=True)

    p = os.path.join(_ROOT, "data", "backtest", "b68d_htf_confirm.json")
    json.dump(out, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
