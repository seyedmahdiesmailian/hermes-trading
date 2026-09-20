"""b213 — is the SOURCE CHANNEL of a signal a tradeable edge?

WHY THIS EXISTS
---------------
The forwarder (forwarder/main.py) fans 7 source channels into one Telegram
group, prefixing every message with "[💬 از {channel}]". The decision path
then throws that away: signal_parser never extracts it and
signal_decision.evaluate_signal has no source term at all. Every channel is
scored as if it were equally trustworthy.

data/radin/ holds a per-channel replay of 7665 historical signals, so the
question "does the source predict profitability?" is answerable from data
the repo already ships — no live risk, no new feed.

WHAT IT MEASURES (read-only; writes ONE ledger, touches no trading state)
------------------------------------------------------------------------
  1. Per-channel expectancy, win rate, payoff ratio and a t-stat.
  2. Chronological quartiles per channel — an edge that only exists in one
     quartile is a streak, not an edge.
  3. HONEST out-of-sample test: choose channels on the FIRST half only,
     then score that choice on the SECOND half. No lookahead.

THE RESULT (2026-09-19, and the reason nothing is wired yet)
------------------------------------------------------------
Win rate is a trap here: gtmofx wins 73.7% of its signals and still LOSES
money (payoff 0.16 — the 31 losses average -7.81 against +1.23 wins).
Expectancy, not win rate, is the thing to weight.

But the naive rule "trade only channels that were profitable in the first
half" FAILED out-of-sample: -426.9 versus trading everything. Three of the
seven channels flip sign between halves (radin -286 -> +478, olivex -44 ->
+46, goldsystem +28 -> -3). Selecting on a noisy half-sample buys the
noise. A stricter, tightening-only rule (veto a channel only when n>=60 AND
t<=-2, i.e. a PROVEN loser) selects nobody on the first half, so it is a
no-op out-of-sample and cannot be claimed as an improvement either.

Only goldfree (t=3.46) and gtmofx (t=-2.19) are individually distinguishable
from zero across the full sample, and only goldfree is stable in all four
quartiles.

VERDICT: the source signal is REAL but not yet SEPARABLE from noise at this
sample size. Per b68/b74 house protocol this stays unwired until the
pre-registered close condition below is met. Shipping it today would be
curve-fitting.

PRE-REGISTERED CLOSE CONDITION (decide before seeing more data)
---------------------------------------------------------------
Wire a per-source term into evaluate_signal only when, for a given channel,
BOTH halves of the then-available history agree in sign AND the full-sample
|t| >= 2 AND n >= 100. First action when it fires is TIGHTENING ONLY: veto
or shrink proven losers. Never enlarge a lot because a channel looks good.

Usage:  python3 scripts/b213_source_channel_census.py [--json]
"""
from __future__ import annotations

import csv
import glob
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "backtest" / "b213_source_channel_census.json"

MIN_N_FOR_VETO = 60      # a half-sample smaller than this cannot convict
T_VETO = -2.0            # ... and it must be a statistically proven loser
QUARTILES = 4


def _channel_name(path: str) -> str:
    base = os.path.basename(path)
    return (base.replace("replay_", "").replace("replay", "radin")
                .replace(".csv", ""))


def load_channels(root: Path = ROOT) -> dict[str, list[tuple[str, float]]]:
    """(date, pnl_ladder) per channel, chronologically sorted.

    Rows the replay marked as skipped are excluded: they were never traded,
    so crediting or blaming their PnL would measure a counterfactual.
    """
    out: dict[str, list[tuple[str, float]]] = {}
    for f in sorted(glob.glob(str(root / "data" / "radin" / "replay*.csv"))):
        rows: list[tuple[str, float]] = []
        with open(f, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if (r.get("skip") or "").strip() not in ("", "0", "False", "false"):
                    continue
                try:
                    rows.append((r["date"], float(r["pnl_ladder"])))
                except (KeyError, TypeError, ValueError):
                    continue
        if rows:
            rows.sort()
            out[_channel_name(f)] = rows
    return out


def stats(seg: list[tuple[str, float]]) -> dict:
    n = len(seg)
    if n == 0:
        return {"n": 0, "total": 0.0, "avg": 0.0, "win_pct": 0.0,
                "t_stat": 0.0, "payoff": 0.0}
    pnl = [p for _, p in seg]
    total = sum(pnl)
    avg = total / n
    sd = math.sqrt(sum((p - avg) ** 2 for p in pnl) / (n - 1)) if n > 1 else 0.0
    t = avg / (sd / math.sqrt(n)) if sd > 0 else 0.0
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(losses) / len(losses) if losses else 0.0
    return {"n": n, "total": round(total, 2), "avg": round(avg, 3),
            "win_pct": round(100 * len(wins) / n, 1),
            "t_stat": round(t, 2),
            "avg_win": round(aw, 2), "avg_loss": round(al, 2),
            "payoff": round(abs(aw / al), 2) if al else 0.0}


def build(channels: dict) -> dict:
    per = {c: stats(rows) for c, rows in channels.items()}

    quartiles = {}
    for c, rows in channels.items():
        n = len(rows)
        quartiles[c] = [
            {"from": seg[0][0][:10], "to": seg[-1][0][:10],
             **{k: stats(seg)[k] for k in ("n", "total", "win_pct")}}
            for i in range(QUARTILES)
            if (seg := rows[i * n // QUARTILES:(i + 1) * n // QUARTILES])
        ]

    # sign stability across halves — the cheapest lie-detector for an "edge"
    halves, flips = {}, []
    for c, rows in channels.items():
        n = len(rows)
        a, b = stats(rows[:n // 2]), stats(rows[n // 2:])
        halves[c] = {"first": a, "second": b}
        if (a["total"] > 0) != (b["total"] > 0):
            flips.append(c)

    def second_half_total(chs):
        return round(sum(stats(channels[c][len(channels[c]) // 2:])["total"]
                         for c in chs), 2)

    allc = list(channels)
    naive_pick = [c for c in allc if halves[c]["first"]["total"] > 0]
    veto_pick = [c for c in allc
                 if halves[c]["first"]["n"] >= MIN_N_FOR_VETO
                 and halves[c]["first"]["t_stat"] <= T_VETO]

    oos = {
        "naive_positive_half_rule": {
            "chosen_on_first_half": naive_pick,
            "second_half_all": second_half_total(allc),
            "second_half_chosen": second_half_total(naive_pick),
            "delta": round(second_half_total(naive_pick)
                           - second_half_total(allc), 2),
        },
        "tightening_only_loser_veto": {
            "vetoed_on_first_half": veto_pick,
            "second_half_all": second_half_total(allc),
            "second_half_kept": second_half_total(
                [c for c in allc if c not in veto_pick]),
            "delta": round(second_half_total([c for c in allc if c not in veto_pick])
                           - second_half_total(allc), 2),
        },
    }

    led = {"per_channel": per, "quartiles": quartiles, "halves": halves,
           "sign_flips": flips, "out_of_sample": oos,
           "params": {"MIN_N_FOR_VETO": MIN_N_FOR_VETO, "T_VETO": T_VETO}}
    led["_self_check_problems"] = self_check(led)
    return led


def self_check(led: dict) -> list[str]:
    """Guard the CLAIMS this census is cited for (b127 reproduction style)."""
    problems = []
    naive = led["out_of_sample"]["naive_positive_half_rule"]
    if naive["delta"] >= 0:
        problems.append(
            "naive half-sample selection no longer loses out-of-sample — the "
            "'do not wire source weighting yet' conclusion must be re-read")
    if not led["sign_flips"]:
        problems.append(
            "no channel flips sign between halves — the instability that "
            "justifies waiting is gone; re-evaluate the close condition")
    gf = led["per_channel"].get("goldfree", {})
    if gf and gf.get("t_stat", 0) < 2:
        problems.append("goldfree is no longer the one stable positive edge")
    return problems


def main(write: bool = True) -> dict:
    led = build(load_channels())
    if write:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(led, indent=1, ensure_ascii=False),
                          encoding="utf-8")
    return led


if __name__ == "__main__":
    ledger = main()
    if "--json" in sys.argv:
        print(json.dumps(ledger, indent=1, ensure_ascii=False))
    else:
        print(f"{'channel':12s} {'n':>5s} {'win%':>6s} {'total':>9s} "
              f"{'avg':>7s} {'payoff':>7s} {'t':>6s}")
        print("-" * 60)
        for c, s in sorted(ledger["per_channel"].items(),
                           key=lambda kv: -kv[1]["total"]):
            print(f"{c:12s} {s['n']:5d} {s['win_pct']:6.1f} {s['total']:9.1f} "
                  f"{s['avg']:7.2f} {s['payoff']:7.2f} {s['t_stat']:6.2f}")
        print("-" * 60)
        o = ledger["out_of_sample"]
        print(f"sign flips between halves: {ledger['sign_flips']}")
        print(f"naive 'positive first half' rule, out-of-sample delta: "
              f"{o['naive_positive_half_rule']['delta']:+.1f}  <- FAILS")
        print(f"tightening-only loser veto, out-of-sample delta:       "
              f"{o['tightening_only_loser_veto']['delta']:+.1f}  "
              f"(vetoed: {o['tightening_only_loser_veto']['vetoed_on_first_half'] or 'nobody'})")
        print(f"self-check: {ledger['_self_check_problems'] or 'clean'}")
