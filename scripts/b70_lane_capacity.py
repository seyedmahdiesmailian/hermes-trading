#!/usr/bin/env python3
"""b70 ADDITIVE-LANE CAPACITY ANALYSIS (read-only; nothing here wires live).

b68 round 4 left the pdh_break_w10 arm in an odd place: it LOSES the funnel's
merit bar on the cached 3000 M15 set (0.627 vs 0.854 exp_R) but BEAT the
funnel on one fresh 6000-bar fetch (0.640 vs 0.576), and the additive-lane
probe (funnel first, arm only on bars the funnel leaves empty, one position
at a time = the live MAX_OPEN_POSITIONS=1 model) raised total R by +7.8%
while diluting per-trade R by -0.017R and worsening DD (7.0R vs 5.0R).
That is a CAPACITY question, not an expectancy question. This script settles
it with the four measurements b70 demands:

1. REPLICATION — the lane replay on the cached set AND three NON-OVERLAPPING
   fresh 6000-bar windows (the single fresh set that made the arm look good
   is one sample; the b68 round-1 METHOD RULE applies to lanes too).
2. LIVE SLOT OCCUPANCY — MAX_OPEN_POSITIONS=1 means the lane can only trade
   when the funnel's slot is FREE; measured from the real execution_log +
   trade_journal (not from the backtest), plus the share of 15-min master
   ticks that find a position open.
3. SAFETY-PATH IMPACT — the extra trades flow into the SAME kill-switch
   inputs: CONSECUTIVE_LOSSES_LIMIT=4 (engines/kill_switch.py) and the
   5%-of-balance daily loss. Reported as max loss streak and worst rolling
   24h R for funnel-only vs lane, per dataset.
4. BLOCKING — the grade-gate precedent (2026-08-30 audit: a C-grade arm that
   occupied the single slot blocked later B setups): count funnel setups
   that appear WHILE an arm trade is open in the lane replay, deduped into
   episodes, with grade breakdown.

Funnel signals come from engines.backtest_real.strategy_signal — the exact
live-parity funnel (parity by construction, no hand-copied gates) — and all
exit management runs through engines.backtest.backtest_ohlc with the live
b60 ladder, same as every b68 round.
"""
import os
import sys
import json
import bisect
import datetime
import csv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))   # b65: a BridgeClient consumer owns its env

from bridge_client import BridgeClient                    # noqa: E402
from engines.backtest import backtest_ohlc                # noqa: E402
from engines.backtest_real import fetch_all_ohlc, strategy_signal  # noqa: E402
from engines.trade_management import _partial_close_fraction  # noqa: E402
from engines.kill_switch import CONSECUTIVE_LOSSES_LIMIT, DAILY_LOSS_LIMIT_PCT  # noqa: E402
from scripts import b68e_pdh_lab as lab                   # noqa: E402
from scripts.b68e_pdh_lab import pdh_break                # noqa: E402

SPREAD = 0.20
WINDOW = 6000
STOP_ATR = 1.0                       # the w10 arm — the only lane candidate
LADDER = dict(partial_share_fn=lambda t: _partial_close_fraction(t),
              trail_after_partial=0.5, tp1_position=0.50,
              partial_tp1_share=0.5, breakeven_at_r=0.0)
# live risk sizing context (execution_log risk_usd ~ 50-102$ on a ~4983$ demo)
RISK_USD_TYPICAL = 100.0


def _utc(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)


# ────────────────────────── signal pre-passes ──────────────────────────

def repoint_lab(rows):
    """Rebuild the PDH levels for THIS dataset and repoint the lab module
    (same pattern as b68e_confirm: pdh_break closes over module globals)."""
    buckets = {}
    for r in rows:
        buckets.setdefault(lab.trading_day(r["time"]), []).append(r)
    days = sorted(buckets)
    levels = {}
    for k in range(1, len(days)):
        prev = buckets[days[k - 1]]
        if len(prev) >= 40:
            levels[days[k]] = (max(x["high"] for x in prev),
                               min(x["low"] for x in prev))
    lab.M15 = rows
    lab.IDX = {r["time"]: n for n, r in enumerate(rows)}
    lab.LEVELS = levels
    return levels


def funnel_signals(m15, h1, h4):
    """{bar_index: signal} from the LIVE-PARITY funnel, no lookahead:
    windows are cut at the bar's own time with bisect (the b68e list-scan
    was O(n) per bar; with 20k-bar context arrays it must not be)."""
    h1t = [r.get("time", 0) for r in h1]
    h4t = [r.get("time", 0) for r in h4]
    out = {}
    for i, row in enumerate(m15):
        bt = row.get("time", 0)
        j1 = bisect.bisect_right(h1t, bt)
        j4 = bisect.bisect_right(h4t, bt)
        hw = h1[max(0, j1 - 80):j1]
        h4w = h4[max(0, j4 - 80):j4]
        mw = m15[max(0, i - 120):i + 1]
        s = strategy_signal(row, hw, h4w, i, m15_window=mw)
        if s:
            out[i] = s
    return out


def arm_signals(rows, stop_atr=STOP_ATR):
    out = {}
    for i in range(30, len(rows)):
        s = pdh_break(i, stop_atr)
        if s:
            out[i] = s
    return out


def lane_signals(f_sig, a_sig):
    """funnel priority: the arm may only take a bar the funnel leaves empty."""
    out = dict(a_sig)
    out.update(f_sig)          # funnel wins on a same-bar collision
    return out


def live_gate_ok(s):
    """the two gates a funnel signal must pass to actually TRADE live:
    gate 6 min_rr=1.5 (auto_executor MIN_RISK_REWARD) and gate 7
    MIN_SETUP_GRADE='B' (grade string compares alphabetically, A<B<C)."""
    if str(s.get("grade") or "").upper() > "B":
        return False
    risk = abs(float(s["entry"]) - float(s["sl"]))
    return risk > 0 and abs(float(s["tp"]) - float(s["entry"])) / risk >= 1.5


# ────────────────────────── replay + stats ──────────────────────────

def replay(rows, sigs, min_rr=0.0, min_grade=None):
    idx = {r["time"]: n for n, r in enumerate(rows)}
    res = backtest_ohlc(rows, lambda row: sigs.get(idx.get(row.get("time"), -1)),
                        min_rr=min_rr, min_grade=min_grade,
                        spread=SPREAD, **LADDER)
    return res


def r_series(res):
    out = []
    for t in res.get("trade_log", []):
        risk = abs(float(t["entry"]) - float(t.get("orig_sl") or t["sl"])) or 1
        out.append((t, float(t["pnl"]) / risk))
    return out


def stats(res, rows):
    ser = r_series(res)
    if not ser:
        return {"n": 0}
    rs = [r for _, r in ser]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = abs(sum(losses) / len(losses)) if losses else 0.001
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    # max consecutive losing trades (kill-switch input #3: >=4 halts)
    streak = mx = 0
    for r in rs:
        streak = streak + 1 if r <= 0 else 0
        mx = max(mx, streak)
    # worst rolling 24h in R (kill-switch input #1 proxy: 5% of balance;
    # at ~100$ risk on ~4983$ balance that is ~2.5R/day)
    worst_day = 0.0
    for k, (t, _) in enumerate(ser):
        t0 = rows[t["exit_index"]]["time"]
        acc = 0.0
        for t2, r2 in ser[k:]:
            if rows[t2["exit_index"]]["time"] > t0 + 86400:
                break
            acc += r2
        worst_day = min(worst_day, acc)
    return {"n": len(rs),
            "wr": round(100 * len(wins) / len(rs), 1),
            "payoff": round(avg_w / avg_l, 2),
            "exp_R": round(sum(rs) / len(rs), 3),
            "tot_R": round(sum(rs), 1),
            "dd_R": round(-dd, 1),
            "max_loss_streak": mx,
            "worst_24h_R": round(worst_day, 1)}


def blocked_funnel(res, f_sig, a_sig, gap_bars=3):
    """Funnel setups that appeared while an ARM trade held the slot.
    Consecutive signal bars of the same setup are ONE episode (the monitor
    re-emits market_entry_now every tick while the plan is valid), so the
    count is setups, not ticks."""
    log = res.get("trade_log", [])
    blocked = 0
    by_grade = {}
    for t in log:
        if str(t.get("style") or "") != "pdh_break":
            continue
        lo, hi = t["entry_index"] + 1, t["exit_index"]
        bars = [j for j in f_sig if lo <= j <= hi]
        if not bars:
            continue
        bars.sort()
        episodes = 1
        for prev, cur in zip(bars, bars[1:]):
            if cur - prev > gap_bars:
                episodes += 1
        blocked += episodes
        for j in bars:
            g = str(f_sig[j].get("grade") or "?")
            by_grade[g] = by_grade.get(g, 0) + 1
    arm_fires_while_funnel_free = sum(
        1 for j in a_sig if j not in f_sig)
    return {"blocked_funnel_episodes": blocked,
            "blocked_funnel_signal_bars": len([j for j in f_sig
                                               if any(t["entry_index"] < j <= t["exit_index"]
                                                      for t in log
                                                      if str(t.get("style") or "") == "pdh_break")]),
            "blocked_by_grade_bars": by_grade,
            "arm_bars_outside_funnel": arm_fires_while_funnel_free}


# ────────────────────────── live occupancy (point 2) ──────────────────────────

def live_occupancy():
    """From the REAL execution_log (entries that reached the broker) and
    trade_journal (close epochs): how often is the single slot occupied?
    The lane can only trade in the gaps, so this bounds its real throughput."""
    entries = []
    p = os.path.join(_ROOT, "data", "xau_plan", "execution_log.csv")
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("dry_run") == "False" and row.get("result_ok") == "True":
                at = datetime.datetime.fromisoformat(row["at"])
                entries.append(at.timestamp())
    closes = []
    p = os.path.join(_ROOT, "data", "xau_plan", "trade_journal.csv")
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                closes.append(float(row["close_time"]))
            except (ValueError, TypeError):
                pass
    entries.sort()
    closes.sort()
    if not entries or not closes:
        return {"entries": len(entries), "note": "no journal closes yet"}
    # Pairing under MAX_OPEN_POSITIONS=1: no two entries overlap, so every
    # journal close in [entry_k, entry_k+1) belongs to position k. Partial
    # exits (HermesPartial rows) mean the FIRST close is not the end of the
    # interval — but journal gaps (closes detected late/batched) mean the
    # LAST close can over-extend. Report BOTH bounds, never a fake point value.
    def pair(rule):
        out = []
        for k, e in enumerate(entries):
            nxt = entries[k + 1] if k + 1 < len(entries) else float("inf")
            mine = [c for c in closes if e <= c < nxt]
            if mine:
                out.append((e, mine[0] if rule == "first" else max(mine)))
        return out
    iv_first, iv_last = pair("first"), pair("last")
    intervals = iv_last
    span_start, span_end = entries[0], max(c for _, c in intervals) if intervals else entries[-1]
    # market-open intervals per calendar day (UTC): Mon-Thu 00-24, Fri 00-22,
    # Sat closed, Sun 23-24 (XAUUSD Sun 23:00 -> Fri 22:00, backlog rule)
    def day_open(d):
        dow = d.weekday()                                   # Mon=0 .. Sun=6
        mid = datetime.datetime.combine(d, datetime.time(), datetime.timezone.utc)
        if dow in (0, 1, 2, 3):
            return mid, mid + datetime.timedelta(days=1)
        if dow == 4:
            return mid, mid + datetime.timedelta(hours=22)
        if dow == 6:
            return mid + datetime.timedelta(hours=23), mid + datetime.timedelta(days=1)
        return None
    open_min = 0.0
    open_ticks = 0
    d = datetime.datetime.fromtimestamp(span_start, datetime.timezone.utc).date()
    end = datetime.datetime.fromtimestamp(span_end, datetime.timezone.utc)
    while datetime.datetime.combine(d, datetime.time(), datetime.timezone.utc) <= end:
        win = day_open(d)
        if win:
            a, b = win
            oa, ob = max(a.timestamp(), span_start), min(b.timestamp(), span_end)
            if ob > oa:
                open_min += (ob - oa) / 60
                open_ticks += int((ob - oa) // 900)
        d += datetime.timedelta(days=1)
    def occ_pct(iv):
        return round(100 * sum(c - e for e, c in iv) / 60 / open_min, 1) if open_min else None

    def is_open(t):
        w = day_open(datetime.datetime.fromtimestamp(t, datetime.timezone.utc).date())
        return bool(w) and w[0].timestamp() <= t < w[1].timestamp()
    all_ticks = [t for t in range(int(span_start), int(span_end), 900)]
    open_ticks_l = [t for t in all_ticks if is_open(t)]
    occ_ticks = [t for t in open_ticks_l
                 if any(e <= t <= c for e, c in intervals)]
    return {"entries_executed": len(entries),
            "closed_intervals": len(intervals),
            "span_days": round((span_end - span_start) / 86400, 2),
            "market_open_hours": round(open_min / 60, 1),
            "slot_occupied_pct_lower": occ_pct(iv_first),
            "slot_occupied_pct_upper": occ_pct(iv_last),
            "ticks_with_position_pct": round(100 * len(occ_ticks) / max(1, len(open_ticks_l)), 1),
            "median_trade_minutes": round(sorted((c - e) for e, c in intervals)[len(intervals) // 2] / 60, 1) if intervals else None}


# ────────────────────────── datasets ──────────────────────────

def load_cached():
    d = json.load(open(os.path.join(_ROOT, "data/backtest/ab_aggressive_data.json")))
    return {"cached_3000": (d["M15"], d["H1"], d["H4"])}


def load_fresh():
    bridge = BridgeClient()
    m15 = fetch_all_ohlc(bridge, "XAUUSD", "M15", 18000 + WINDOW)
    h1 = fetch_all_ohlc(bridge, "XAUUSD", "H1", 20000)
    h4 = fetch_all_ohlc(bridge, "XAUUSD", "H4", 5000)
    if not m15 or not h1 or not h4:
        raise SystemExit("bridge fetch failed (read-only): "
                         f"{len(m15)}/{len(h1)}/{len(h4)}")
    out = {}
    for k, name in ((0, "fresh_w1_recent"), (1, "fresh_w2_middle"),
                    (2, "fresh_w3_older")):
        hi = len(m15) - k * WINDOW
        lo = hi - WINDOW
        if lo < 0:
            break
        out[name] = (m15[lo:hi], h1, h4)
    return out


def analyze(name, rows, h1, h4):
    repoint_lab(rows)
    f_sig = funnel_signals(rows, h1, h4)
    a_sig = arm_signals(rows)
    f_ok = {j: s for j, s in f_sig.items() if live_gate_ok(s)}
    # LAB-comparable lane (no gates applied — continuity with b68e numbers)
    ln_sig = lane_signals(f_sig, a_sig)
    # LIVE-PARITY lane: only funnel signals that would ACTUALLY trade live
    # (grade<=B, rr>=1.5) claim the slot; a gated-out funnel signal leaves
    # the bar to the arm, exactly like live gate 6/7 rejections do.
    ln_sig_p = dict(a_sig)
    ln_sig_p.update(f_ok)
    res_f = replay(rows, f_sig)
    res_a = replay(rows, a_sig)
    res_l = replay(rows, ln_sig)
    # LIVE-PARITY pass (gate 6 min_rr=1.5 + gate 7 grade>=B): the lane would
    # have to pass the same stack, and this is the pass the capacity decision
    # is actually made on.
    res_fp = replay(rows, f_sig, min_rr=1.5, min_grade="B")
    res_lp = replay(rows, ln_sig_p, min_rr=1.5, min_grade="B")
    sf, sa, sl = stats(res_f, rows), stats(res_a, rows), stats(res_l, rows)
    sfp, slp = stats(res_fp, rows), stats(res_lp, rows)
    # blocking: setups the live funnel would REALLY trade (f_ok) that appear
    # while an arm trade holds the slot — the grade-gate precedent question.
    blk = blocked_funnel(res_lp, f_ok, a_sig)
    lane_trades = [t for t in res_l.get("trade_log", [])]
    arm_taken = sum(1 for t in lane_trades if str(t.get("style")) == "pdh_break")
    lane_trades_p = [t for t in res_lp.get("trade_log", [])]
    arm_taken_p = sum(1 for t in lane_trades_p if str(t.get("style")) == "pdh_break")
    return {"dataset": name,
            "bars": len(rows),
            "range": [str(_utc(rows[0]["time"])), str(_utc(rows[-1]["time"]))],
            "funnel_signals": len(f_sig), "arm_signals": len(a_sig),
            "funnel_signals_live_tradable": len(f_ok),
            "funnel_only": sf, "arm_only": sa, "lane": sl,
            "live_parity": {"funnel_only": sfp, "lane": slp,
                            "lane_arm_trades_taken": arm_taken_p,
                            "blocking": blk},
            "lane_arm_trades_taken": arm_taken,
            "blocking": blk}


def main():
    datasets = load_cached()
    datasets.update(load_fresh())
    results = {}
    print(f"{'dataset':18s} {'arm':10s} {'n':>4s} {'exp_R':>7s} {'tot_R':>7s} "
          f"{'dd_R':>5s} {'streak':>6s} {'24hR':>6s}")
    for name, (rows, h1, h4) in datasets.items():
        r = analyze(name, rows, h1, h4)
        results[name] = r
        for arm in ("funnel_only", "arm_only", "lane"):
            s = r[arm]
            if s.get("n"):
                print(f"{name:18s} {arm:10s} {s['n']:4d} {s['exp_R']:7.3f} "
                      f"{s['tot_R']:7.1f} {s['dd_R']:5.1f} "
                      f"{s['max_loss_streak']:6d} {s['worst_24h_R']:6.1f}", flush=True)
        for arm in ("funnel_only", "lane"):
            s = r["live_parity"][arm]
            if s.get("n"):
                print(f"{name:18s} {'LP:' + arm:10s} {s['n']:4d} {s['exp_R']:7.3f} "
                      f"{s['tot_R']:7.1f} {s['dd_R']:5.1f} "
                      f"{s['max_loss_streak']:6d} {s['worst_24h_R']:6.1f}", flush=True)
        b = r["blocking"]
        print(f"{'':18s} blocked funnel episodes: {b['blocked_funnel_episodes']} "
              f"(grades by bar: {b['blocked_by_grade_bars']}), "
              f"arm trades taken in lane: {r['lane_arm_trades_taken']}", flush=True)
    occ = live_occupancy()
    results["_live_occupancy"] = occ
    results["_safety_context"] = {
        "kill_switch_consecutive_losses_limit": CONSECUTIVE_LOSSES_LIMIT,
        "kill_switch_daily_loss_pct": DAILY_LOSS_LIMIT_PCT,
        "risk_usd_typical": RISK_USD_TYPICAL,
        "note": "daily-loss halt in R ≈ 5% of balance / risk per trade"}
    print("live occupancy:", json.dumps(occ))
    p = os.path.join(_ROOT, "data", "backtest", "b70_lane_capacity.json")
    json.dump(results, open(p, "w"), indent=2)
    print("saved:", os.path.abspath(p))


if __name__ == "__main__":
    main()
