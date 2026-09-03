#!/usr/bin/env python3
"""b64 META-FILTER STUDY - don't replace the funnel, condition it.

Research (arXiv 2511.08571 trend-momentum regime on gold; quantifiedstrategies
session stats; luxalgo time-of-day) says the cheapest edge on GOLD is a
regime/time filter ON TOP of an existing signal. So: run the exact live
funnel once, then slice its trades by hour / day-of-week / ATR regime /
grade / style and see whether dropping the worst slices raises expectancy
per trade WITHOUT killing sample size.

Output: for each candidate filter, exp_R with-filter vs without, n kept,
n dropped, and the improvement. Only filters with n>=40 kept and
>=0.15R improvement are worth wiring into live.
"""
import json, os, sys, statistics
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge_client import BridgeClient
from engines.backtest import backtest_ohlc
from engines.backtest_real import fetch_all_ohlc, strategy_signal
from engines.trade_management import _partial_close_fraction

COUNT = 6000
TF = "M15"
SPREAD = 0.20
LADDER = dict(partial_share_fn=lambda t: _partial_close_fraction(t),
              trail_after_partial=0.5, tp1_position=0.50,
              partial_tp1_share=0.5, breakeven_at_r=0.0)


def r_stats(trades, rows):
    rs, wins = [], 0
    for t in trades:
        risk = abs(float(t["entry"]) - float(t.get("orig_sl") or 0))
        if risk <= 0:
            continue
        pnl = float(t["pnl"]) / risk
        rs.append(pnl)
        if pnl > 0:
            wins += 1
    if not rs:
        return dict(n=0, wr=0.0, exp=0.0, tot=0.0)
    return dict(n=len(rs), wr=100.0 * wins / len(rs),
                exp=statistics.mean(rs), tot=sum(rs))


def main():
    bridge = BridgeClient()
    data = {TF: fetch_all_ohlc(bridge, "XAUUSD", TF, COUNT),
            "H1": fetch_all_ohlc(bridge, "XAUUSD", "H1", COUNT),
            "H4": fetch_all_ohlc(bridge, "XAUUSD", "H4", COUNT)}
    rows = data[TF]
    print("bars:", len(rows), flush=True)
    idx_of = {r["time"]: n for n, r in enumerate(rows)}

    def signal_fn(row):
        i = idx_of.get(row.get("time"))
        if i is None:
            return None
        bt = row.get("time", 0)
        hw = [r for r in data["H1"] if r.get("time", 0) <= bt][-80:]
        h4w = [r for r in data["H4"] if r.get("time", 0) <= bt][-80:]
        return strategy_signal(row, hw, h4w, i,
                               m15_window=rows[max(0, i - 120):i + 1])

    res = backtest_ohlc(rows, signal_fn, min_rr=0.0, spread=SPREAD, **LADDER)
    trades = res["trade_log"]
    print("total trades:", len(trades), flush=True)

    # enrich each trade with context at ENTRY bar
    for t in trades:
        bar = rows[t["entry_index"]]
        dt = datetime.fromtimestamp(bar["time"], tz=timezone.utc)
        t["hour"] = dt.hour
        t["dow"] = dt.weekday()  # 0=Mon
        # ATR regime: 14-bar ATR over prior bars at entry
        w = rows[max(0, t["entry_index"] - 15):t["entry_index"] + 1]
        trs = [max(float(r["high"]) - float(r["low"]),
                   abs(float(r["high"]) - float(w[j]["close"])))
               for j, r in enumerate(w) if j > 0]
        t["atr"] = statistics.mean(trs) if trs else 0.0
        # trend strength: |close - close[20]| / ATR20
        back = rows[max(0, t["entry_index"] - 20):t["entry_index"] + 1]
        if len(back) >= 10 and t["atr"] > 0:
            t["trend"] = abs(float(back[-1]["close"]) - float(back[0]["close"])) / (t["atr"] * 4)
        else:
            t["trend"] = 0.0
    atr_med = statistics.median([t["atr"] for t in trades]) if trades else 0

    base = r_stats(trades, rows)
    print(f"\nBASELINE (live funnel): n={base['n']} WR={base['wr']:.0f}% exp={base['exp']:.3f}R tot={base['tot']:.0f}R\n")

    def slice_report(name, keep_fn):
        kept = [t for t in trades if keep_fn(t)]
        drop = [t for t in trades if not keep_fn(t)]
        k = r_stats(kept, rows)
        d = r_stats(drop, rows)
        gain = k["exp"] - base["exp"]
        flag = " <<< WIRE IT" if k["n"] >= 40 and gain >= 0.15 else ""
        print(f"{name:34s} keep n={k['n']:3d} exp={k['exp']:+.3f}R ({gain:+.3f}) | dropped n={d['n']:3d} exp={d['exp']:+.3f}R{flag}")
        return dict(name=name, kept=k, dropped=d, gain=gain)

    out = []
    # time-of-day slices (UTC)
    out.append(slice_report("skip asia 0-6h", lambda t: t["hour"] >= 7))
    out.append(slice_report("only london+ny 7-21h", lambda t: 7 <= t["hour"] <= 21))
    out.append(slice_report("skip 21-23h late", lambda t: t["hour"] < 21))
    out.append(slice_report("only 12-17h (NY overlap)", lambda t: 12 <= t["hour"] <= 17))
    # day-of-week
    out.append(slice_report("skip friday after 14h", lambda t: not (t["dow"] == 4 and t["hour"] >= 14)))
    out.append(slice_report("skip monday before 8h", lambda t: not (t["dow"] == 0 and t["hour"] < 8)))
    # volatility regime
    out.append(slice_report("ATR above median only", lambda t: t["atr"] >= atr_med))
    out.append(slice_report("ATR below median only", lambda t: t["atr"] < atr_med))
    # trend regime
    out.append(slice_report("trend>=0.5 (directional)", lambda t: t["trend"] >= 0.5))
    out.append(slice_report("trend<0.5 (chop) DROPS?", lambda t: t["trend"] < 0.5))
    # grade / style
    for g in ("A", "B", "C"):
        out.append(slice_report(f"grade {g} only", lambda t, g=g: t.get("grade") == g))
    styles = sorted({t.get("style", "?") for t in trades})
    for s in styles:
        if s and s != "?":
            out.append(slice_report(f"style {s} only", lambda t, s=s: t.get("style") == s))
            out.append(slice_report(f"WITHOUT style {s}", lambda t, s=s: t.get("style") != s))

    json.dump(dict(bars=len(rows), baseline=base, filters=out,
                   trades=[{k: t.get(k) for k in
                            ("hour", "dow", "atr", "trend", "grade", "style",
                             "entry_index", "side", "entry", "orig_sl", "pnl")}
                           for t in trades]),
              open("data/backtest/b64_metafilters_m15.json", "w"), indent=1)
    print("\nsaved: data/backtest/b64_metafilters_m15.json")


if __name__ == "__main__":
    main()
