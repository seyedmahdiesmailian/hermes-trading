#!/usr/bin/env python3
"""b182 — EXIT POLICY BACKTEST: does closing 100% at TP1-mid eat our winners?

Filed from the 2026-09-08 ops audit of the last 33 live positions (broker
deals, net per position): 22 wins summing +652.95 (avg +29.68) against 11
losses summing -659.16 (avg -59.92). Payoff ratio 0.50 — the exits are
cutting winners at ~half the size of the losers, even though every plan is
built at RR 1.5+. Per-exit census: realized winners average +0.53R, realized
losers -1.01R. The loss side is EXACTLY as planned; the win side is being
amputated.

Cause is structural, not a bug — two decisions that each tested true but
never together:
  * b55 (2026-08): close 100% at TP1 (evidence taken when TP1 was still the
    FULL target),
  * b60 (2026-08-26): ladder TP1 = midpoint between entry and final target.
Together: every B/C trade realizes +0.75R and dies while the plan's final
target (1.5R) sits unvisited. engines/trade_management.py
_partial_close_fraction returns 1.0 for every non-strong-runner grade, and
the strong-runner branch (grade A AND momentum>=0.8 AND structure healthy)
has never fired live (b55's own comment says so; live grade mix is 23 B / 9 A).

This script measures alternative exits on two populations, replaying REAL
M5 bar paths from the bridge (30000 bars, cached):

  live         — the 26 executed trades with plan rows (execution_log.csv
                 joined to broker position opens): did the manager harvest
                 less than the plan promised?
  replay_all   — every non-skip leg in data/radin/replay.csv (~656 signal
                 legs, 2026-06-08..09-04), geometry rebuilt with the SAME
                 ladder builder the live watchdog uses
                 (engines/trade_management.build_tp_ladder).

Policies (all start with the plan SL untouched):
  P0_live     full exit at TP1-mid  (today's B/C behaviour — the baseline)
  P1_half_be  50% at TP1-mid, SL to breakeven, rest to final target
  P2_be_lock  50% at TP1-mid, SL to entry+0.15R (the A-grade lock), rest final
  P3_ride     no TP1 exit — full position to final target or SL
  P4_runner   P2 + trail the runner at 0.3x risk off bar CLOSES, armed one
              bar after TP1 (no same-bar look-ahead)
  P5_mid_cut  full exit, but TP1 drawn at 60% of the way to final (deeper cut)

Ambiguity rule: if a bar touches BOTH the SL and a target, the SL is assumed
to have filled FIRST (conservative — a policy can only be hurt, never
flattered). Commission: 0.06$/0.01lot round trip (the real broker shape:
0.03$/0.01lot/side). Bars are held in data/backtest/b182_m5_bars.json so
reruns are offline and byte-stable.

Decision rule (pre-registered, b54b/b55d style): adopt a challenger over
P0_live only if it wins the TOTALS on both populations, wins >=60% of 13
weekly slices of replay_all, and never loses a week by more than 10% of that
week's gross in more than 4 slices.

Output: data/backtest/b182_exit_policy.json + printed verdict table.
Every derived block is reproducible from the cached bars + CSVs (b127 rule).
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines.trade_management import build_tp_ladder  # noqa: E402

BARS_CACHE = ROOT / "data" / "backtest" / "b182_m5_bars.json"
LEDGER_OUT = ROOT / "data" / "backtest" / "b182_exit_policy.json"
REPLAY_CSV = ROOT / "data" / "radin" / "replay.csv"
EXEC_CSV = ROOT / "data" / "xau_plan" / "execution_log.csv"

HORIZON_BARS = 864          # 72h on M5 — beyond this the thesis is stale
COMMISSION_PER_001 = 0.06   # round trip, $ per 0.01 lot
DOLLARS_PER_LOT_POINT = 100.0  # XAUUSD: 1.00 move on 1.00 lot = $100
POLICIES = ["P0_live", "P1_half_be", "P2_be_lock", "P3_ride", "P4_runner",
            "P5_mid_cut"]
WEEK_BARS = 2016            # one week of M5 bars


def _num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ─────────────────────────── bar fetch / cache ───────────────────────────
def load_bars(offline: bool = False):
    if BARS_CACHE.exists():
        blob = json.loads(BARS_CACHE.read_text())
        return [tuple(b) for b in blob["bars"]]  # (time, high, low, close)
    if offline:
        raise SystemExit("no cached bars and offline=True")
    from bridge_client import BridgeClient
    from env_loader import load_dotenv
    load_dotenv(ROOT / ".env")
    data = BridgeClient().get_rates(symbol="XAUUSD", timeframe="M5",
                                    count=30000)["data"]
    bars = [(int(b["time"]), float(b["high"]), float(b["low"]),
             float(b["close"])) for b in data]
    bars.sort()
    BARS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    BARS_CACHE.write_text(json.dumps({"bars": bars}))
    return bars


def first_bar_at_or_after(times, t):
    lo, hi = 0, len(times)
    while lo < hi:
        mid = (lo + hi) // 2
        if times[mid] < t:
            lo = mid + 1
        else:
            hi = mid
    return lo


# ─────────────────────────── the simulator ───────────────────────────
def simulate(policy: str, side: str, entry: float, sl: float,
             tp_levels: list[float], lots: float,
             bars, start_i: int):
    """Walk M5 bars forward; apply one named exit policy.

    Returns dict(R=net R-multiple after commission, exit_kind, exit_time,
    bars_held). R is measured against the ORIGINAL risk |entry-sl|.
    Conservative same-bar rule: SL is checked BEFORE targets.
    """
    risk = abs(entry - sl)
    if risk <= 0 or not tp_levels:
        return None
    is_buy = side.upper() == "BUY"
    final = tp_levels[-1]
    tp1 = tp_levels[0]
    if policy == "P5_mid_cut":
        tp1 = entry + (final - entry) * 0.60
    sign = 1.0 if is_buy else -1.0
    value = risk * DOLLARS_PER_LOT_POINT * lots  # $ risked = 1.0R

    cur_sl = sl
    closed_r = 0.0                 # R already banked from partials
    open_share = 1.0
    filled_tp1 = False
    best = entry
    trail_arm_i = None  # trail arms only on bars AFTER the TP1 bar
    end = min(start_i + HORIZON_BARS, len(bars))

    def close_all(price, kind, i):
        nonlocal open_share, closed_r
        move_r = sign * (price - entry) / risk
        closed_r += move_r * open_share
        open_share = 0.0
        if kind == "SL" and filled_tp1:
            kind = "SL_be" if abs(price - entry) < 1e-9 else \
                   ("SL_lock" if abs(sign * (price - entry) - 0.15 * risk) < 1e-6
                    else "SL_trail")
        return {"R": round(closed_r - commission_r(value, lots), 4),
                "exit_kind": kind, "exit_time": bars[i][0],
                "bars_held": i - start_i}

    for i in range(start_i, end):
        _t, hi, lo, cl = bars[i]
        # 1) stop first (conservative)
        if is_buy and lo <= cur_sl:
            return close_all(cur_sl, "SL", i)
        if not is_buy and hi >= cur_sl:
            return close_all(cur_sl, "SL", i)
        # 2) TP1 events
        if not filled_tp1:
            hit = (is_buy and hi >= tp1) or (not is_buy and lo <= tp1)
            if hit:
                filled_tp1 = True
                trail_arm_i = i + 1
                if policy == "P0_live":
                    return close_all(tp1, "TP1_full", i)
                if policy == "P3_ride":
                    filled_tp1 = False  # P3 ignores TP1 entirely
                else:
                    share = 1.0 if policy == "P5_mid_cut" else 0.5
                    closed_r += (sign * (tp1 - entry) / risk) * share
                    open_share -= share
                    if open_share <= 0:
                        return {"R": round(closed_r - commission_r(value, lots), 4),
                                "exit_kind": "TP1_full", "exit_time": bars[i][0],
                                "bars_held": i - start_i}
                    if policy == "P1_half_be":
                        cur_sl = entry
                    elif policy in ("P2_be_lock", "P4_runner"):
                        cur_sl = entry + sign * 0.15 * risk
        # 3) final target with whatever remains
        if policy != "P0_live" and open_share > 0:
            hit = (is_buy and hi >= final) or (not is_buy and lo <= final)
            if hit:
                return close_all(final, "FINAL", i)
        # 4) trail (P4 only): ratchets off the bar CLOSE, arms the bar AFTER
        # TP1 — taking the same bar's high would assume it closed at its peak.
        best = max(best, cl) if is_buy else min(best, cl)
        if policy == "P4_runner" and filled_tp1 and trail_arm_i is not None \
                and i >= trail_arm_i:
            trail = best - sign * 0.3 * risk
            if (is_buy and trail > cur_sl) or (not is_buy and trail < cur_sl):
                cur_sl = trail
    return close_all(bars[end - 1][3], "TIMEOUT", end - 1)


def commission_r(value_risked: float, lots: float) -> float:
    comm = COMMISSION_PER_001 * (lots / 0.01)
    return comm / value_risked if value_risked else 0.0


# ─────────────────────────── populations ───────────────────────────
def live_trades(bars, times):
    """execution_log rows joined to broker position opens (26 real trades)."""
    from bridge_client import BridgeClient
    from env_loader import load_dotenv
    load_dotenv(ROOT / ".env")
    deals = BridgeClient().get_history_deals(symbol="XAUUSD", days=30)["data"]
    opens = {}
    for d in deals:
        if int(d.get("entry") or 0) != 0:
            continue
        pid = int(d["position_id"])
        if pid not in opens:
            opens[pid] = {"t": int(d["time"]), "entry": float(d["price"]),
                          "lots": float(d["volume"]),
                          "side": str(d["type"]).upper()}
    out = []
    seen = set()
    for r in csv.DictReader(EXEC_CSV.open()):
        tk = r.get("ticket", "")
        if not tk.isdigit() or int(tk) not in opens or tk in seen:
            continue
        f = opens[int(tk)]
        entry, sl, tp = f["entry"], _num(r["sl"]), _num(r["tp"])
        if sl <= 0 or tp <= 0:
            continue
        seen.add(tk)
        i = first_bar_at_or_after(times, f["t"])
        if i >= len(times):
            continue
        out.append({"id": tk, "side": f["side"], "entry": entry, "sl": sl,
                    "tp": tp, "ladder": build_tp_ladder(entry, f["side"], tp, [tp]),
                    "lots": f["lots"], "i": i, "grade": r.get("grade", "?")})
    return out


def replay_legs(bars, times):
    legs = []
    for r in csv.DictReader(REPLAY_CSV.open()):
        side, entry, sl = r["side"], _num(r["entry"]), _num(r["sl"])
        rr_fin = _num(r["rr_ladder"])
        if side not in ("BUY", "SELL") or entry <= 0 or sl <= 0 or rr_fin <= 0:
            continue
        if r.get("verdict") == "skip":
            continue
        sign = 1.0 if side == "BUY" else -1.0
        final = entry + sign * abs(entry - sl) * rr_fin
        ladder = build_tp_ladder(entry, side, final, [final])
        t = csv_date(r["date"])
        i = first_bar_at_or_after(times, t)
        if i >= len(times) or i + 12 >= len(times):
            continue
        legs.append({"id": f"{r['date'][:16]}-{side}-{entry}", "side": side,
                     "entry": entry, "sl": sl, "tp": final, "ladder": ladder,
                     "lots": 0.01, "i": i})
    return legs


def csv_date(iso: str) -> int:
    from datetime import datetime
    return int(datetime.fromisoformat(iso).timestamp())


# ─────────────────────────── aggregation ───────────────────────────
def run_population(trades, bars, policies, sim_cache=None):
    res = {}
    for p in policies:
        rows, kinds = [], defaultdict(int)
        for t in trades:
            sim = simulate(p, t["side"], t["entry"], t["sl"], t["ladder"],
                           t["lots"], bars, t["i"])
            if sim is None:
                continue
            if sim_cache is not None:
                sim_cache[(t["id"], p)] = sim["R"]
            risk_usd = abs(t["entry"] - t["sl"]) * DOLLARS_PER_LOT_POINT * t["lots"]
            rows.append((t["i"], sim["R"], sim["R"] * risk_usd))
            kinds[sim["exit_kind"]] += 1
        rows.sort()  # equity curve must read in open-trade order
        R = [r for _i, r, _u in rows]
        n = len(R)
        wins = [r for r in R if r > 0]
        losses = [r for r in R if r <= 0]
        eq = peak = dd = 0.0
        for r in R:
            eq += r
            peak = max(peak, eq)
            dd = min(dd, eq - peak)
        res[p] = {
            "n": n,
            "total_R": round(sum(R), 2),
            "total_usd": round(sum(u for _i, _r, u in rows), 2),
            "avg_R": round(sum(R) / n, 3) if n else 0.0,
            "win_rate": round(len(wins) / n, 3) if n else 0.0,
            "avg_win_R": round(sum(wins) / len(wins), 3) if wins else 0.0,
            "avg_loss_R": round(sum(losses) / len(losses), 3) if losses else 0.0,
            "maxDD_R": round(dd, 2),
            "exits": dict(kinds),
        }
    return res


def weekly_table(trades, bars, policies, sim_cache):
    """Slice replay legs into WEEK_BARS buckets; report per-week R per policy.
    sim_cache is the dict built by run_population — reuses the exact walks."""
    weeks = defaultdict(lambda: defaultdict(list))
    for t in trades:
        wk = t["i"] // WEEK_BARS
        for p in policies:
            R = sim_cache.get((t["id"], p))
            if R is not None:
                weeks[wk][p].append(R)
    out = {}
    for wk in sorted(weeks):
        out[f"w{wk}"] = {p: round(sum(v), 2) for p, v in weeks[wk].items()
                         if p in policies}
    return out


def main() -> int:
    bars = load_bars()
    times = [b[0] for b in bars]
    live = live_trades(bars, times)
    replay = replay_legs(bars, times)

    ledger = {"_note": "R vs original plan risk; SL-first on ambiguous bars; "
                       "commission in; ladder=build_tp_ladder (live parity); "
                       "P3/P4/P2 differ only in post-TP1 handling",
              "counts": {"live": len(live), "replay_all": len(replay)}}
    ledger["live"] = run_population(live, bars, POLICIES)
    replay_cache = {}
    ledger["replay_all"] = run_population(replay, bars, POLICIES, replay_cache)
    ledger["weekly"] = weekly_table(replay, bars, POLICIES, replay_cache)

    # decision rule (pre-registered in the docstring)
    verdicts = {}
    wk = ledger["weekly"]
    for p in POLICIES[1:]:
        wins_wk = sum(1 for v in wk.values() if v[p] > v["P0_live"])
        big_losses = sum(1 for v in wk.values()
                         if v[p] < v["P0_live"] - 0.10 * (abs(v["P0_live"]) + 1))
        both_better = (ledger["live"][p]["total_R"] > ledger["live"]["P0_live"]["total_R"]
                       and ledger["replay_all"][p]["total_R"] > ledger["replay_all"]["P0_live"]["total_R"])
        verdicts[p] = {"weekly_wins": f"{wins_wk}/{len(wk)}",
                       "weeks_blown>10pct": big_losses,
                       "totals_better_both_pops": both_better,
                       "adopt": both_better and wins_wk >= 0.6 * len(wk)
                       and big_losses <= 4}
    ledger["verdicts"] = verdicts

    LEDGER_OUT.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_OUT.write_text(json.dumps(ledger, indent=1, ensure_ascii=False))

    print(f"populations: live={len(live)} replay={len(replay)}  "
          f"(bars={len(bars)})\n")
    print(f"{'policy':12s} {'live R':>8s} {'live $':>8s} {'rep R':>9s} "
          f"{'rep $':>9s} {'wr':>5s} {'avgW':>6s} {'avgL':>6s} "
          f"{'maxDD':>6s}  verdict")
    for p in POLICIES:
        L, Rp = ledger["live"][p], ledger["replay_all"][p]
        v = verdicts.get(p, {})
        tag = ("ADOPT" if v.get("adopt") else
               ("BASE" if p == "P0_live" else "reject"))
        extra = f"{v.get('weekly_wins','-')} wk" if v else ""
        print(f"{p:12s} {L['total_R']:>8.1f} {L['total_usd']:>8.0f} "
              f"{Rp['total_R']:>9.1f} {Rp['total_usd']:>9.0f} "
              f"{Rp['win_rate']*100:>4.0f}% {Rp['avg_win_R']:>6.2f} "
              f"{Rp['avg_loss_R']:>6.2f} {Rp['maxDD_R']:>6.1f}  {tag} {extra}")
    print(f"\nledger → {LEDGER_OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
