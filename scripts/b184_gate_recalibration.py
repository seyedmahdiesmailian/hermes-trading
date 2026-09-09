#!/usr/bin/env python3
"""b184 — GATE RECALIBRATION UNDER THE b182 EXIT: is b147's "do not loosen" stale?

Why this exists: b147 (2026-09-08, scripts/b147_ladder_gate_counterfactual.py)
measured "loosen the channel-signal gate to ladder RR" as -$73 and the stance
became DECISION (A): gate unchanged. But b147 priced every counterfactual
trade under the OLD exit — P0_live, close 100% at TP1-mid, the amputation
policy b182 replaced. The loser side of that math is unaffected by the exit
(the plan SL was always honored), but the WINNER side was worth 0.5x what a
plan says. Under the deployed exit (half at TP1-mid + broker TP for the rest,
~+1.0R per winner) the break-even win rate drops from ~57% to ~50%, and b147
itself measured the ladder-admits population at 53.6% win — the old verdict
sat inside a ~1-2% band that the exit change is exactly big enough to flip.
The stance line "re-open ~100 live trades" predates any counterfactual; this
is the honest re-open, on the same machine b182 built.

What the machine knows (measured here, not assumed):
  - data/radin/replay.csv: 660 non-skip channel legs with rr_tp1 (the signal's
    OWN first-target ratio) and rr_ladder (full ladder). The current gate
    admits legs with rr_tp1>=1.0 — 16 of 660. "Loosen to ladder" admits
    642 of 660: the population is dominated by rr_tp1=0.5 ladder signals.
  - b147's own numbers: ladder-admits population = 53.6% win (TP1 lens),
    avg loss -1.04R. At old realized winners +0.75R that is
    0.536*0.75 - 0.464*1.04 = -0.10R/trade -> the -$73.
    At b182 realized winners ~+1.0R and losers -1.01R:
    0.536*1.00 - 0.464*1.01 = +0.06R/trade -> flips sign IF the win-rate
    holds, which is exactly what this script measures on real M5 paths.

Method: import b182's harness (same bars, same simulator, same commission,
same SL-first ambiguity rule) and run THREE populations x the four
exit-relevant policies (P0 old amputation, P2 deployed lock, P4 runner,
P3 no-management floor):
  g16      — today's gate on replay (rr_tp1>=1.0, n=16): tiny but honest
  l642     — loosened gate (rr_ladder>=1.5, n=642)
  l100     — intermediate: rr_ladder>=1.5 AND rr_tp1>=0.4 (deeper first rung)
Per population per policy: total R, avg winner, avg loser, win rate, weekly
slices. The adoption question is NOT "is loosened positive" — it is
"under WHICH exit does which gate pay", and whether P2 (deployed) or P4
(backtest winner) is the right production pairing for a wider funnel.

Pre-registered decision rule: recommend loosening only if the l642 (or l100)
population is positive under BOTH deployed-P2 and P4 with >=55% winning weeks
AND g16 stays positive (no pressure to loosen to save a dying gate). Otherwise
keep DECISION (A) and say so — a stale verdict that re-measures to the SAME
answer is still worth having measured.

Read-only on the repo; writes data/backtest/b184_gate_recalibration.json.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "b182", ROOT / "scripts" / "b182_exit_policy_backtest.py")
b182 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b182)  # module-level is defs + path constants only

from engines.trade_management import build_tp_ladder  # noqa: E402

REPLAY_CSV = ROOT / "data" / "radin" / "replay.csv"
OUT = ROOT / "data" / "backtest" / "b184_gate_recalibration.json"
POLICIES = ["P0_live", "P2_be_lock", "P4_runner", "P3_ride"]
WEEK_BARS = b182.WEEK_BARS


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def gate_populations():
    """Replay legs bucketed by which gate version admits them.

    Geometry identical to b182.replay_legs (same build_tp_ladder on the same
    final target) so the only variable is ADMISSION."""
    bars = b182.load_bars(offline=True)
    times = [b[0] for b in bars]
    pops = {"g16": [], "l642": [], "l100": []}
    for r in csv.DictReader(REPLAY_CSV.open()):
        side, entry, sl = r["side"], _num(r["entry"]), _num(r["sl"])
        rr_fin, rr_t1 = _num(r["rr_ladder"]), _num(r["rr_tp1"])
        if side not in ("BUY", "SELL") or not entry or not sl or not rr_fin:
            continue
        if rr_fin <= 0 or abs(entry - sl) < 0.05:
            continue
        if r.get("verdict") == "skip":
            continue
        sign = 1.0 if side == "BUY" else -1.0
        final = entry + sign * abs(entry - sl) * rr_fin
        ladder = build_tp_ladder(entry, side, final, [final])
        i = b182.first_bar_at_or_after(times, b182.csv_date(r["date"]))
        if i >= len(times) or i + 12 >= len(times):
            continue
        leg = {"id": f"{r['date'][:16]}-{side}-{entry}", "side": side,
               "entry": entry, "sl": sl, "tp": final, "ladder": ladder,
               "lots": 0.01, "i": i, "rr_tp1": rr_t1, "rr_ladder": rr_fin}
        if rr_t1 is not None and rr_t1 >= 1.0:
            pops["g16"].append(leg)
        if rr_fin >= 1.5:
            pops["l642"].append(leg)
            if rr_t1 is not None and rr_t1 >= 0.4:
                pops["l100"].append(leg)
    return bars, pops


def run(bars, legs, policies):
    res = {}
    for p in policies:
        rs = []
        for t in legs:
            sim = b182.simulate(p, t["side"], t["entry"], t["sl"],
                                t["ladder"], t["lots"], bars, t["i"])
            if sim:
                rs.append((sim, t))
        wins = [s["R"] for s, _ in rs if s["R"] > 0]
        losses = [s["R"] for s, _ in rs if s["R"] <= 0]
        weeks = defaultdict(float)
        for s, t in rs:
            wk = (t["i"]) // WEEK_BARS
            weeks[wk] += s["R"]
        res[p] = {
            "n": len(rs),
            "total_R": round(sum(s["R"] for s, _ in rs), 2),
            "total_usd": round(sum(s["R"] * 2.0 for s, _ in rs), 1),  # $2 per 0.01lot * R at ~$20 typical... see note
            "win_rate": round(100.0 * len(wins) / len(rs), 1) if rs else None,
            "avg_win_R": round(sum(wins) / len(wins), 3) if wins else None,
            "avg_loss_R": round(sum(losses) / len(losses), 3) if losses else None,
            "weeks": len(weeks),
            "weeks_positive": sum(1 for v in weeks.values() if v > 0),
            "week_R": {str(k): round(v, 2) for k, v in sorted(weeks.items())},
        }
    return res


def main():
    # NOTE on total_usd: R here is per original risk; with $~100 risked per
    # live trade a 0.01-lot replay leg's R is notional. We report R first,
    # dollars only as R x $100 (the live risk unit) for scale intuition.
    bars, pops = gate_populations()
    out = {"note": "b184: gate recalibration under b182 exit; USD col = R x $100 "
                   "(live risk unit), NOT the replay leg's own $",
           "pops": {}}
    for name, legs in pops.items():
        out["pops"][name] = {"n_legs": len(legs)}
        out["pops"][name].update(run(bars, legs, POLICIES))
    # b147 echo: the same populations priced under the OLD exit for contrast
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    hdr = f"{'pop':6s} {'policy':12s} {'n':>4s} {'totR':>7s} {'win%':>5s} {'avgW':>6s} {'avgL':>7s} {'wks+':>5s}"
    print(hdr)
    for name in pops:
        for p in POLICIES:
            d = out["pops"][name].get(p)
            if not d or not d.get("n"):
                continue
            print(f"{name:6s} {p:12s} {d['n']:>4d} {d['total_R']:>7.2f} "
                  f"{d['win_rate']:>5.1f} {d['avg_win_R']:>6.2f} "
                  f"{d['avg_loss_R']:>7.2f} {d['weeks_positive']:>2d}/{d['weeks']:<3d}")
    print(f"ledger: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
