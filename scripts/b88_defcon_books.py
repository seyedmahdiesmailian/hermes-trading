#!/usr/bin/env python3
"""b88 (b68 round 20) — MEASURE THE GATE, NOT JUST THE ARM: DEFCON as books,
and as the ONE gate whose input is the book's own history (todo b87's queue:
after min_rr (b84) and range-kill (b86) comes DEFCON, then cooldown, then
market hours).

Why this gate is different from the two already measured. min_rr and the
range-kill threshold read the SIGNAL (geometry, regime, confidence): their
population is fixed and the gate is a slice of it. DEFCON reads the RESULTS —
loss_streak, daily_pnl and the last 10 closed DEALS — so it can only bind after
the system has already traded, and it is the only live gate that forms a
feedback loop with its own book. Measuring it therefore needs a REPLAY of the
funnel's own trade sequence through the live classifier (engines.defcon,
imported, never restated), not a predicate on a static population.

What is measured per leg (cached + b74's four independent windows, b71 harness,
b80 live gates):

  defcon_off        the funnel as every earlier round measured it — the b83
                    parity row: it MUST reproduce b80's gradeB_rr15 exactly.
  state@entry       the DEFCON level the live executor would have seen at each
                    entry, built from the deals the live feed actually carries
                    (see the window-shape probe below).
  kept_defcon       entries the gate allows, as its own book (slot contention
                    re-priced by the real engine, b84's _book pattern).
  dropped_defcon   the RED-blocked entries, as their own book — what the gate
                    would be saving, in R.
  REDUNDANCY (b87) for every block, was the kill switch's OWN consecutive-loss
                    trigger already armed? A block that sits behind a halt is a
                    shadow, not a second lock on the door.
  WINDOW SHAPE      the two input-contract probes (below) — how many deals in
                    the live window are not trades, and what the gate sees on
                    the first cycle of a UTC day.

Two input-contract facts this round was written to price (both found by reading
the live path, both reproduced here on real data):

  (1) DEALS vs TRADES. engines/risk.compute_performance_state sets
      `recent_closed = (closed_trades or [])[-10:]` straight from the bridge's
      history-deals feed, and engines/defcon.classify_exits classifies EVERY
      deal. But MT5 history deals come in pairs: an opening deal (entry=0,
      profit 0, comment 'Hermes') and a closing deal (entry=1). So a 10-deal
      window holds ~5 closed trades, `total` is inflated ~2x and `sl_ratio` is
      diluted ~2x. The YELLOW/RED clause is documented as "half the closed
      trades died at SL" (sl_ratio >= 0.5); with the denominator counting
      opening deals too, reaching 0.5 requires ALL of the window's exits to be
      SLs. The probe counts, per leg, how many entries would change level if
      the window held only closing deals — that is the price of the fix, and
      the reason it is NOT applied here: correcting the denominator also makes
      the `total >= 5` / `total >= 3` count preconditions HARDER (they are
      today satisfied by ~2.5 and ~1.5 real trades), so the change is not
      monotone in one direction. A gate whose sensitivity moves both ways is a
      human decision (hard rule: never weaken a risk gate).

  (2) THE DAY-ROLLOVER BLIND CYCLE. compute_performance_state has two returns.
      The same-day branch writes `recent_closed`; the day-rollover branch
      (first cycle of each new UTC day) returns a dict WITHOUT the key. So on
      the first cycle of every day, auto_executor's DEFCON check gets
      `recent_closed = []` -> total 0 -> GREEN by construction, whatever
      yesterday did. That is exactly the cycle on which a "you are bleeding,
      do not open today's first trade" gate is worth having. This round FIXES
      that one (carry the window through the rollover — strictly more sight,
      never less) and pins it with tests.

Discipline: b71 harness (plain/ladder/ladder_ts + hold columns), b74
all-windows rule, b77 chronological read (W4 oldest -> W1 newest), b78 BUY/SELL
mix of the trades actually taken, b80 live gates imported, b83 re-MEASURE and
reproduce b80, b84 books, b87 redundancy row.

HARD RULES honoured: read-only research, nothing here is imported by the live
path, no gate is weakened (the only live change this round ships is the
rollover window carry-through, which can only ever make DEFCON see MORE
history), and every recommendation is a PROPOSAL for a human.

Known limitation, disclosed in the ledger: the kept/dropped books are slices of
the OFF-book's population, so they do not model the cascade — after a RED block
frees a slot and changes which trades exist, the later states would differ.
Same limitation b84/b86 accepted for their books; the state@entry replay is
the honest artefact, the books are its price tag.
"""
import bisect
import json
import os
import sys
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from engines import lab_harness as lh                            # noqa: E402
from engines.auto_executor import (                              # noqa: E402
    MIN_RISK_REWARD, MIN_SETUP_GRADE, MAX_RISK_PER_TRADE_PCT)
from engines.defcon import classify_exits, compute_insights      # noqa: E402
from engines.kill_switch import CONSECUTIVE_LOSSES_LIMIT         # noqa: E402
from engines.risk import compute_performance_state               # noqa: E402
from engines.backtest_real import strategy_signal                # noqa: E402
from scripts.b68r_grade_ladder_lab import side_mix               # noqa: E402

OUT = "data/backtest/b88_defcon_books.json"
PARITY = "data/backtest/b80_gate_parity.json"
WINDOWS = ("W1", "W2", "W3", "W4")
CHRONO = ("W4", "W3", "W2", "W1")
LEGS = ("cached",) + WINDOWS
RANGE_KILL_CONF = 0.35          # the live literal (build_live_plan)
WINDOW_DEALS = 10               # risk.py: recent_closed = last 10 DEALS


def _row(arm_row):
    return {"trades": arm_row["trades"], "exp_R": arm_row.get("exp_R"),
            "net_R": arm_row.get("net_R"), "WR%": arm_row.get("WR%"),
            "maxDD_R": arm_row.get("maxDD_R"),
            "mean_hold_bars": arm_row.get("mean_hold_bars")}


def sig_fn(sigs, idx_of):
    def fn(row):
        return sigs.get(idx_of.get(int(row.get("time", 0)), -1))
    return fn


def funnel_signals(m15, h1, h4):
    """The live funnel's own signal population at the live gate settings."""
    h1t = [r.get("time", 0) for r in h1]
    h4t = [r.get("time", 0) for r in h4]
    sigs = {}
    for i, row in enumerate(m15):
        bt = row.get("time", 0)
        j1 = bisect.bisect_right(h1t, bt)
        j4 = bisect.bisect_right(h4t, bt)
        s = strategy_signal(row, h1[max(0, j1 - 80):j1],
                            h4[max(0, j4 - 80):j4], i,
                            m15_window=m15[max(0, i - 120):i + 1],
                            range_kill_conf=RANGE_KILL_CONF)
        if s:
            sigs[i] = s
    return sigs


def book_trades(m15, fn):
    """The funnel's trade sequence under the live ladder + live time exit.

    Calls the REAL engine (lh.backtest_ohlc with lh.LADDER), exactly the way
    side_mix does — this is not a hand-written copy of the funnel, it is the
    funnel's own trade_log, which is what the gate's inputs must be built from.
    """
    res = lh.backtest_ohlc(m15, fn, min_rr=MIN_RISK_REWARD,
                           min_grade=MIN_SETUP_GRADE, spread=lh.SPREAD,
                           **lh.LADDER, time_stop_bars=lh.live_time_stop_bars(m15))
    return res.get("trade_log", [])


# ── the gate's own input contract, reproduced from the live feed ───────────
def exit_comment(t):
    """The MT5 comment the live system would have written on this exit.

    Broker-side stops arrive as '[sl <price>]'; our own closes (partial,
    breakeven scratch, time exit) carry a Hermes* comment. classify_exit()
    keys off exactly these strings, so the replay feeds it real shapes.
    """
    r = t.get("exit_reason")
    if r in ("sl", "sl_part", "be") and t.get("pnl", 0) < 0:
        return f"[sl {t.get('sl')}]"
    if r == "tp":
        return f"[tp {t.get('tp')}]"
    if r == "sl":
        return f"[sl {t.get('sl')}]"
    return "HermesClose"


def deals_for(trades, m15):
    """Expand closed trades into the deal feed the bridge actually returns.

    One opening deal (profit 0) + one closing deal per position, sorted by
    TIME and ticketed in that order: MT5 hands out tickets as deals happen, so
    a position opened early and closed late contributes an opening deal early
    and a closing deal later. Feeding DEFCON in entry order instead would put
    a future closing deal inside a past window.
    """
    raw = []
    for k, t in enumerate(trades):
        et = int(m15[int(t["entry_index"])]["time"])
        xt = int(m15[int(t["exit_index"])]["time"])
        raw.append((et, 0, {"entry": 0, "profit": 0.0, "comment": "Hermes",
                            "time": et, "type": t["side"], "side": t["side"]}))
        raw.append((xt, 1, {"entry": 1, "profit": float(t["pnl"]),
                            "comment": exit_comment(t), "time": xt,
                            "type": t["side"], "side": t["side"]}))
    raw.sort(key=lambda r: (r[0], r[1]))
    return [dict(d, ticket=i + 1) for i, (_, _, d) in enumerate(raw)]


def replay_states(m15, trades, balance=5000.0):
    """Per entry: the DEFCON level the live executor would have seen.

    The state (loss_streak, daily_pnl, recent_closed) is produced by
    engines.risk.compute_performance_state — the SAME function the live cycle
    calls on the SAME feed shape — so the replay cannot drift from production on
    how a streak or a daily PnL is counted. The window handed to DEFCON is
    therefore the live 10-DEAL window, opening deals included, which is what
    makes the deals-vs-trades dilution visible instead of theoretical.
    """
    deals = deals_for(trades, m15)
    deal_times = [int(d["time"]) for d in deals]
    out = []
    state = {}
    seen_days: set[str] = set()
    # Fold order must be EXIT order, not entry order. A trade opened before
    # this one can still close after it, and folding its result early would
    # hand DEFCON a future loss — the exact lookahead the b77 chrono rule exists
    # to prevent, in the one gate that reads the book's own history.
    by_exit = sorted(range(len(trades)),
                     key=lambda j: int(m15[int(trades[j]["exit_index"])]["time"]))
    exit_ts = [int(m15[int(t["exit_index"])]["time"]) for t in trades]
    ptr = 0               # next trade (in exit order) to fold into `state`
    for k, t in enumerate(trades):
        entry_time = int(m15[int(t["entry_index"])]["time"])
        entry_day = datetime.fromtimestamp(entry_time, tz=timezone.utc).date().isoformat()
        # fold every trade that had ALREADY exited before this entry, one
        # compute_performance_state call per closed trade (as the live cycle
        # does per tick). The feed handed to it is the live deal list.
        while ptr < len(by_exit) and exit_ts[by_exit[ptr]] < entry_time:
            pt = exit_ts[by_exit[ptr]]
            pday = datetime.fromtimestamp(pt, tz=timezone.utc).date().isoformat()
            # the feed the live cycle would hold at that moment: every deal
            # that had already happened, chronologically
            state = compute_performance_state(state, pday, balance,
                                              deals[:bisect_right(deal_times, pt)])
            ptr += 1
        window = state.get("recent_closed") or []
        streak = int(state.get("loss_streak", 0) or 0)
        pnl = float(state.get("daily_pnl", 0.0) or 0.0)
        ins_live = compute_insights(loss_streak=streak, daily_pnl=pnl,
                                    balance=balance,
                                    classified=classify_exits(window))
        # corrected window: closing deals only (the documented "closed trades")
        exits_only = [d for d in window if str(d.get("entry")) != "0"]
        ins_fix = compute_insights(loss_streak=streak, daily_pnl=pnl,
                                   balance=balance,
                                   classified=classify_exits(exits_only))
        # PRE-FIX blind cycle: the first cycle of a new UTC day returned a
        # state dict with NO recent_closed and loss_streak/daily_pnl zeroed, so
        # compute_insights saw (0, 0.0, []) -> GREEN by construction. The
        # entries that could land in that one-cycle window are exactly the
        # FIRST entry of their UTC day (an upper bound: the blind cycle is ~5
        # min wide, so most of them were in fact sighted).
        first_of_day = entry_day not in seen_days
        seen_days.add(entry_day)
        ins_pre = (compute_insights(loss_streak=0, daily_pnl=0.0,
                                    balance=balance, classified=[])
                   if first_of_day else ins_live)
        risk = abs(float(t["entry"]) - float(t.get("orig_sl") or t["sl"]))
        out.append({
            "entry_index": int(t["entry_index"]),
            "entry_time": entry_time,
            "side": str(t["side"]).upper(),
            "R": round(float(t["pnl"]) / risk if risk else 0.0, 3),
            "exit_reason": t.get("exit_reason"),
            "loss_streak": int(state.get("loss_streak", 0) or 0),
            "daily_pnl": float(state.get("daily_pnl", 0.0) or 0.0),
            "window_deals": len(window),
            "window_exits": sum(1 for d in window if str(d.get("entry")) != "0"),
            "defcon_live": ins_live.get("defcon"),
            "defcon_corrected": ins_fix.get("defcon"),
            "defcon_pre_fix": ins_pre.get("defcon"),
            "entry_day": entry_day,
            "first_entry_of_utc_day": first_of_day,
            "trade_allowed_live": ins_live.get("trade_allowed", True),
            "risk_override_live": ins_live.get("risk_override"),
            "kill_switch_armed": int(state.get("loss_streak", 0) or 0) >= CONSECUTIVE_LOSSES_LIMIT,
        })
    return out


def measure_leg(name, m15, h1, h4):
    sigs = funnel_signals(m15, h1, h4)
    idx_of = {int(r["time"]): i for i, r in enumerate(m15)}
    base = sig_fn(sigs, idx_of)
    arm = lh.run_arm(m15, base, min_rr=MIN_RISK_REWARD, min_grade=MIN_SETUP_GRADE)
    trades = book_trades(m15, base)
    states = replay_states(m15, trades)

    red = {s["entry_index"] for s in states if s["defcon_live"] == "RED"}
    yel = {s["entry_index"] for s in states if s["defcon_live"] == "YELLOW"}
    flip = {s["entry_index"] for s in states
            if s["defcon_corrected"] != s["defcon_live"]}
    # the PRE-FIX blind cycle: entries that were the first of their UTC day and
    # would have been GREEN-by-construction while the sighted state said
    # YELLOW/RED. This is the population the rollover fix re-gives sight to.
    blind = {s["entry_index"] for s in states
             if s["defcon_pre_fix"] != s["defcon_live"]}

    def pred(keep):
        def fn(row):
            s = base(row)
            if not s:
                return None
            i = idx_of.get(int(row.get("time", 0)), -1)
            return s if keep(i) else None
        return fn

    out = {"_bars": len(m15), "_first": int(m15[0]["time"]),
           "_last": int(m15[-1]["time"]),
           "_signals": len(sigs), "_book_trades": len(trades),
           "_defcon_level_mix": dict(Counter(s["defcon_live"] for s in states)),
           "_defcon_corrected_mix": dict(Counter(s["defcon_corrected"] for s in states)),
           "_window_deals_median": (sorted(s["window_deals"] for s in states)[len(states) // 2]
                                    if states else None),
           "_window_exits_median": (sorted(s["window_exits"] for s in states)[len(states) // 2]
                                    if states else None),
           "_entries_with_full_window": sum(1 for s in states
                                            if s["window_deals"] >= WINDOW_DEALS),
           "_first_entry_of_day_count": sum(1 for s in states
                                            if s["first_entry_of_utc_day"]),
           "_blind_cycle_entries": len(blind),
           "_blind_cycle_levels": dict(Counter(
               s["defcon_live"] for s in states
               if s["entry_index"] in blind)),
           "defcon_off": {m: _row(arm[m]) for m in ("plain", "ladder", "ladder_ts")},
           "kept_defcon": _book(m15, pred(lambda i: i not in red), idx_of),
           "dropped_defcon": _book(m15, pred(lambda i: i in red), idx_of),
           "kept_corrected": _book(m15, pred(lambda i: i not in flip), idx_of),
           "dropped_corrected": _book(m15, pred(lambda i: i in flip), idx_of),
           # the population the ROLLOVER FIX re-gives sight to: entries that
           # were the first of their UTC day and whose level the pre-fix code
           # could not see (GREEN by construction). Booked so the fix has a
           # price tag in R, not just a count.
           "blind_cycle_book": _book(m15, pred(lambda i: i in blind), idx_of),
           "_states": states,
           }
    out["defcon_off"]["_mix"] = side_mix(m15, base, min_grade=MIN_SETUP_GRADE)
    # YELLOW exposure: entries that would have traded at half risk
    out["_yellow_entries"] = len(yel)
    out["_red_entries"] = len(red)
    out["_red_blocked_behind_kill_switch"] = sum(
        1 for s in states if s["defcon_live"] == "RED" and s["kill_switch_armed"])
    out["_corrected_stricter_entries"] = sum(
        1 for s in states
        if ["GREEN", "YELLOW", "RED"].index(s["defcon_corrected"]) >
        ["GREEN", "YELLOW", "RED"].index(s["defcon_live"]))
    out["_corrected_looser_entries"] = sum(
        1 for s in states
        if ["GREEN", "YELLOW", "RED"].index(s["defcon_corrected"]) <
        ["GREEN", "YELLOW", "RED"].index(s["defcon_live"]))
    return out


def _book(m15, fn, idx_of):
    arm = lh.run_arm(m15, fn, min_rr=MIN_RISK_REWARD, min_grade=MIN_SETUP_GRADE)
    row = {m: _row(arm[m]) for m in ("plain", "ladder", "ladder_ts")}
    row["_mix"] = side_mix(m15, fn, min_grade=MIN_SETUP_GRADE)
    if arm.get("zero_reason"):
        row["zero_reason"] = arm["zero_reason"]
    return row


def verdict(led):
    v = {}
    # Q1 does the gate bind at all, per leg? (b84 rule 1)
    v["binding"] = {w: {"red_entries": led[w]["_red_entries"],
                        "yellow_entries": led[w]["_yellow_entries"],
                        "levels": led[w]["_defcon_level_mix"],
                        "dropped_book_trades":
                            led[w]["dropped_defcon"]["ladder_ts"]["trades"]}
                   for w in LEGS}
    # Q2 what does it reject, in R? (b81: exp_R AND net_R AND DD together)
    v["dropped_book"] = {w: led[w]["dropped_defcon"]["ladder_ts"] for w in LEGS}
    v["kept_vs_off"] = {w: {
        "kept_exp_R": led[w]["kept_defcon"]["ladder_ts"]["exp_R"],
        "off_exp_R": led[w]["defcon_off"]["ladder_ts"]["exp_R"],
        "kept_trades": led[w]["kept_defcon"]["ladder_ts"]["trades"],
        "off_trades": led[w]["defcon_off"]["ladder_ts"]["trades"]}
        for w in LEGS}
    # Q3 (b87) REDUNDANCY: is a block sitting behind the kill switch's own
    # consecutive-loss trigger? Then DEFCON is not the reason entry stops.
    v["redundancy_vs_kill_switch"] = {
        w: {"red_entries": led[w]["_red_entries"],
            "also_behind_kill_switch": led[w]["_red_blocked_behind_kill_switch"],
            "consecutive_losses_limit": CONSECUTIVE_LOSSES_LIMIT}
        for w in LEGS}
    # Q3b the rollover blind cycle: how many entries were the first of their
    # UTC day, and what did the gate MISS on them (pre-fix vs sighted)?
    v["rollover_blind_cycle"] = {w: {
        "first_entry_of_day": led[w]["_first_entry_of_day_count"],
        "entries_whose_level_the_fix_changes": led[w]["_blind_cycle_entries"],
        "levels_at_those_entries": led[w]["_blind_cycle_levels"],
        "book_trades": led[w]["blind_cycle_book"]["ladder_ts"]["trades"],
        "book_exp_R": led[w]["blind_cycle_book"]["ladder_ts"]["exp_R"],
        "book_net_R": led[w]["blind_cycle_book"]["ladder_ts"]["net_R"]}
        for w in LEGS}
    # Q4 window shape: the deals-vs-trades dilution, priced per leg
    v["window_shape"] = {w: {
        "median_window_deals": led[w]["_window_deals_median"],
        "median_window_exits": led[w]["_window_exits_median"],
        "entries_with_full_10_deal_window": led[w]["_entries_with_full_window"],
        "level_mix_live": led[w]["_defcon_level_mix"],
        "level_mix_corrected": led[w]["_defcon_corrected_mix"],
        "entries_corrected_stricter": led[w]["_corrected_stricter_entries"],
        "entries_corrected_looser": led[w]["_corrected_looser_entries"],
        "book_trades": led[w]["_book_trades"]} for w in LEGS}
    # Q5 b83 integrity: defcon_off must reproduce b80's gradeB_rr15
    par = json.load(open(PARITY))["legs"]
    v["parity_vs_b80"] = {}
    for w in LEGS:
        a = led[w]["defcon_off"]["ladder_ts"]
        b = par[w]["gradeB_rr15"]
        v["parity_vs_b80"][w] = {
            "match": (a["trades"] == b["trades"] and a["exp_R"] == b["exp_R"]
                      and a["net_R"] == b["net_R"]),
            "this_round": {k: a[k] for k in ("trades", "exp_R", "net_R")},
            "b80": {k: b[k] for k in ("trades", "exp_R", "net_R")}}
    v["parity_all_match"] = all(x["match"] for x in v["parity_vs_b80"].values())
    # Q6 b77 chronological read of the gate's own fire rate
    v["chrono"] = {w: {"book_trades": led[w]["_book_trades"],
                       "red": led[w]["_red_entries"],
                       "yellow": led[w]["_yellow_entries"],
                       "off_exp_R": led[w]["defcon_off"]["ladder_ts"]["exp_R"]}
                   for w in CHRONO}
    # Q7 reachability (b86's addition): can learning.py move DEFCON? No knob
    # exists — the thresholds are literals in engines/defcon.py.
    from engines.learning import adjustments
    adj = adjustments()
    v["adaptive_reach"] = {
        "learning_changes_keys": sorted((adj.get("changes") or {}).keys()),
        "learning_can_move_defcon": any("defcon" in k for k in
                                        (adj.get("changes") or {})),
        "thresholds_are_literals_in": "engines/defcon.py compute_insights "
                                      "(loss_streak>=2, closed>=5, sl_ratio>=0.5)",
        "note": ("DEFCON has no knob at all: its triggers are hardcoded and no "
                 "adaptive path touches them. Unlike range-kill (b86) it is not "
                 "shadowed by another gate's population — it is shadowed by the "
                 "kill switch only when it fires."),
    }
    v["mix"] = {w: led[w]["defcon_off"]["_mix"] for w in LEGS}
    return v


def main():
    # Provenance: this ledger's defcon_live column depends on the SHAPE of the
    # state dict engines/risk.compute_performance_state hands DEFCON (the b88
    # rollover fix changes it). Stamp the code that built it so a stale ledger
    # can never pass as current (pinned in tests/test_b88_defcon_books.py).
    import hashlib
    with open(os.path.join(_ROOT, "engines", "risk.py"), "rb") as f:
        risk_sha = hashlib.sha256(f.read()).hexdigest()[:12]
    led = {"_risk_code_sha": risk_sha,
           "_note": "b88 (b68 round 20): DEFCON measured as a FEEDBACK-LOOP book "
                    "— the funnel's own trade sequence replayed through the live "
                    "engines.defcon classifier per entry, kept/dropped books under "
                    "the b71 harness, the b87 redundancy row against the kill "
                    "switch, and the two window-shape probes (deals-vs-trades "
                    "dilution, day-rollover blind cycle). Read-only; no gate "
                    "weakened; the corrected-window row is a PROPOSAL for a human.",
           "_live_gates": {"MIN_RISK_REWARD": MIN_RISK_REWARD,
                           "MIN_SETUP_GRADE": MIN_SETUP_GRADE,
                           "RANGE_KILL_CONF": RANGE_KILL_CONF,
                           "WINDOW_DEALS": WINDOW_DEALS,
                           "CONSECUTIVE_LOSSES_LIMIT": CONSECUTIVE_LOSSES_LIMIT,
                           "MAX_RISK_PER_TRADE_PCT": MAX_RISK_PER_TRADE_PCT},
           "_harness": "b71 (plain/ladder/ladder_ts, live spread 0.20, live 36h "
                       "time exit) + b80 gates + b78 mix + b77 chrono + b74 "
                       "all-windows + b83 reproduce-b80 + b87 redundancy"}
    c = json.load(open("data/backtest/ab_aggressive_data.json"))
    print("##### cached (in-sample, informational) #####", flush=True)
    led["cached"] = measure_leg("cached", c["M15"], c["H1"], c["H4"])
    wins = json.load(open("data/backtest/b68l_independent_windows.json"))
    for w in WINDOWS:
        print(f"##### {w} #####", flush=True)
        led[w] = measure_leg(w, wins[w]["M15"], wins[w]["H1"], wins[w]["H4"])
    led["_verdict"] = verdict(led)

    print("\n=== DEFCON level at each entry (live classifier, live window shape) ===")
    print(f"{'leg':8s} {'book':>6s} {'GREEN':>7s} {'YELLOW':>7s} {'RED':>5s} "
          f"{'off exp_R':>10s} {'kept exp_R':>11s} {'drop exp_R':>11s}")
    for leg in LEGS:
        L = led[leg]
        mix = L["_defcon_level_mix"]
        print(f"{leg:8s} {L['_book_trades']:6d} {mix.get('GREEN', 0):7d} "
              f"{mix.get('YELLOW', 0):7d} {mix.get('RED', 0):5d} "
              f"{L['defcon_off']['ladder_ts']['exp_R']:10.3f} "
              f"{L['kept_defcon']['ladder_ts']['exp_R'] or 0:11.3f} "
              f"{L['dropped_defcon']['ladder_ts']['exp_R'] or 0:11.3f}")
    print("\n=== window shape: deals in the live window vs closed trades ===")
    for leg in LEGS:
        L = led[leg]
        print(f"{leg:8s} median window = {L['_window_deals_median']} deals / "
              f"{L['_window_exits_median']} closed trades; corrected mix "
              f"{L['_defcon_corrected_mix']} (live {L['_defcon_level_mix']})")
    print("\n=== VERDICT ===")
    print(json.dumps({k: v for k, v in led["_verdict"].items() if k != "binding"},
                     indent=1))
    json.dump(led, open(OUT, "w"), indent=1)
    print("\nsaved:", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
