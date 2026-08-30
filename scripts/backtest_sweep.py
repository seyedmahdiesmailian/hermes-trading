#!/usr/bin/env python3
"""Honest re-sweep with spread + next-bar BE, deeper lookbacks, session breakdown."""
import os
import sys
import json
from datetime import datetime, timezone

sys.path.insert(0, '/home/ai/hermes-trading')
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv('/home/ai/hermes-trading/.env')
from bridge_client import BridgeClient
from engines.backtest_real import strategy_signal, fetch_all_ohlc
from engines.backtest import backtest_ohlc

SPREAD = 0.20  # XAUUSD typical demo spread, price units
OUT = '/home/ai/hermes-trading/data/backtest/sweep_results_v2.json'
CHART = '/home/ai/hermes-trading/reports/backtest_charts.png'

bridge = BridgeClient()
results = []


def run(label, n_m15, be=0.5, partial=0.0, min_rr=1.5):
    m15 = fetch_all_ohlc(bridge, "XAUUSD", "M15", n_m15)
    h1 = fetch_all_ohlc(bridge, "XAUUSD", "H1", max(n_m15 // 4, 100))
    h4 = fetch_all_ohlc(bridge, "XAUUSD", "H4", max(n_m15 // 16, 100))
    if not m15:
        print(f"{label}: NO DATA", flush=True)
        return None

    def signal_fn(row):
        bar_time = row.get("time", 0)
        i = m15.index(row)
        hw = [x for x in h1 if x.get("time", 0) <= bar_time][-30:]
        fw = [x for x in h4 if x.get("time", 0) <= bar_time][-15:]
        mw = m15[max(0, i - 119):i + 1]  # rolling M15 window standing in for live M5
        return strategy_signal(row, hw, fw, i, m15_window=mw)

    r = backtest_ohlc(m15, signal_fn, min_rr=min_rr, breakeven_at_r=be,
                      partial_tp1_share=partial, spread=SPREAD)
    r.update({"label": label, "bars": len(m15), "be": be, "partial": partial, "min_rr": min_rr,
              "range_from": datetime.fromtimestamp(m15[0]['time'], tz=timezone.utc).isoformat(),
              "range_to": datetime.fromtimestamp(m15[-1]['time'], tz=timezone.utc).isoformat()})
    # session breakdown of trades
    for t in r["trade_log"]:
        h = datetime.fromtimestamp(m15[t["entry_index"]]["time"], tz=timezone.utc).hour
        t["session"] = "asia" if 0 <= h < 7 else ("newyork" if 13 <= h < 21 else "london")
    results.append(r)
    wr = r["win_rate"] * 100
    wrd = r["win_rate_decided"] * 100
    print(f"{label:34s} trades={r['trades']:3d} win={r['wins']:2d} loss={r['losses']:2d} "
          f"scratch={r['scratches']:2d} WR={wr:5.1f}% (decided {wrd:4.0f}%) pnl={r['net_pnl']:+8.1f}", flush=True)
    return r


run("A: 1500 bars RR1.5 BE0.5", 1500)
run("B: 1500 bars +partial50", 1500, partial=0.5)
run("C: 3000 bars RR1.5 BE0.5", 3000)
run("D: 3000 bars +partial50", 3000, partial=0.5)
run("E: 5000 bars RR1.5 BE0.5", 5000)
run("F: 5000 bars +partial50", 5000, partial=0.5)
run("G: 8000 bars RR1.5 BE0.5", 8000)
run("H: 8000 bars +partial50", 8000, partial=0.5)
run("I: 8000 bars BE0.6", 8000, be=0.6)

json.dump(results, open(OUT, 'w'), indent=2)
print("saved", OUT, flush=True)

# ── session performance on the biggest sample (last run with most trades) ──
big = max(results, key=lambda r: r["trades"])
sess = {}
for t in big["trade_log"]:
    s = sess.setdefault(t["session"], {"n": 0, "pnl": 0.0, "w": 0, "l": 0})
    s["n"] += 1
    s["pnl"] += t["pnl"]
    if t["pnl"] > 0.01:
        s["w"] += 1
    elif t["pnl"] < -0.01:
        s["l"] += 1
print(f"\nSession breakdown ({big['label']}):", flush=True)
for k, v in sorted(sess.items(), key=lambda kv: -kv[1]["n"]):
    print(f"  {k:8s} n={v['n']:3d} win={v['w']:2d} loss={v['l']:2d} pnl={v['pnl']:+8.1f}", flush=True)

# ── charts ──
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(14, 9))
fig.suptitle('Hermes XAUUSD Backtest v2 — spread 0.20 + next-bar BE (conservative)', fontsize=12)

labels = [f"{r['label'].split(':')[0]}\n{r['bars']//1000}k" + ("+p" if r['partial'] else "") for r in results]
wr = [r["win_rate"] * 100 for r in results]
wrd = [r["win_rate_decided"] * 100 for r in results]
pnl = [r["net_pnl"] for r in results]

ax = axes[0][0]
ax.bar(range(len(results)), wr, color='#C99A3C', label='all trades')
ax.bar(range(len(results)), wrd, color='#2E7D32', alpha=0.55, label='decided (no scratch)')
ax.set_title('Win rate %'); ax.legend(fontsize=8)
ax.set_xticks(range(len(results))); ax.set_xticklabels(labels, fontsize=7)
for i, v in enumerate(wr): ax.text(i, v + 1, f'{v:.0f}', ha='center', fontsize=8)

ax = axes[0][1]
ax.bar(range(len(results)), pnl, color=['#2E7D32' if v >= 0 else '#B3261E' for v in pnl])
ax.set_title('Net PnL ($) after spread')
ax.set_xticks(range(len(results))); ax.set_xticklabels(labels, fontsize=7)
for i, v in enumerate(pnl): ax.text(i, v + (3 if v >= 0 else -8), f'{v:+.0f}', ha='center', fontsize=8)

ax = axes[1][0]
ax.bar(range(len(results)), [r["trades"] for r in results], color='#1F2A44')
ax.set_title('Trade count')
ax.set_xticks(range(len(results))); ax.set_xticklabels(labels, fontsize=7)

ax = axes[1][1]
for r in [results[0], results[-2], results[-1]]:
    eq, cum = [0], 0
    for t in r["trade_log"]:
        cum += t["pnl"]; eq.append(cum)
    ax.plot(eq, marker='o', markersize=3, label=r["label"].split(':')[0] + f' {r["bars"]//1000}k')
ax.set_title('Equity curves'); ax.grid(alpha=0.3); ax.legend(fontsize=8)
ax.set_xlabel('trade #'); ax.set_ylabel('cum PnL $')

plt.tight_layout()
plt.savefig(CHART, dpi=110)
print("chart saved", CHART, flush=True)
