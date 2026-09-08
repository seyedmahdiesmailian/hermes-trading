#!/usr/bin/env python3
"""b141 — DAY-ROLLOVER BLIND-WINDOW CENSUS: what exactly does the first cycle of
each UTC day lose, and what would each proposed fix cost?

b140 found the cold-start artifact; b139's progress note widened it. The claim
under test is that `engines.risk.compute_performance_state` returns
`daily_pnl = 0.0 / loss_streak = 0` whenever the stored day != today, so the
FIRST cycle of every UTC day classifies the account "normal" no matter what
yesterday did. This census does not re-argue that in prose — it walks the REAL
broker deal feed through the REAL functions and prints, per day boundary, what
each of the THREE consumers sees:

  1. SCORER/SIZER regime  — engines.risk.assess_account_policy (the lane that
     picks defensive/recovery/locked multipliers, wired live by b136/b140)
  2. DEFCON               — engines.defcon.compute_insights on the same state
     (b88 already carries `recent_closed` through the rollover, so only the
     loss_streak / daily_pnl legs are blind — this measures how much that matters)
  3. KILL SWITCH          — engines.kill_switch.check_kill_switch, which
     hermes_runtime.cycle feeds from performance['daily_pnl'] and
     performance['loss_streak'] (the b139 note's third consumer)

and then prices the two FIX OPTIONS the backlog lists, without shipping either:

  option_a  recompute yesterday's daily_pnl/loss_streak from the 7-day feed on
            the rollover cycle (the backlog's first suggestion)
  option_b  keep the zeros and mark the state cold (a flag a future gate could
            read), i.e. regime/DEFCON see yesterday, the kill switch does not

THE FINDING THIS SCRIPT EXISTS TO CHECK (and does not assume): option_a is
labelled "tightening-neutral" in the backlog. Tightening is allowed; a change of
MEANING is not a side effect to slip past a human gate. If yesterday's loss can
arm the kill switch's DAILY_LOSS_LIMIT_PCT trigger on today's first cycle, then
option_a does not "halve the risk of one cycle" — it converts a per-day loss cap
into a trailing one and can park a COOLDOWN_HOURS halt at 00:00 for damage done
yesterday. That is the same semantic line b88 drew for `loss_streak` ("a human
decision, not a side effect"), so the census measures the halt, it does not
assume it away.

HONEST LIMITS (stated, not hidden):
  * equity is unknown for past days, so the drawdown legs of
    assess_account_policy are neutralised (equity := balance, drawdown 0). The
    census therefore measures ONLY the deal-derived branches (daily_pnl,
    loss_streak) — which is exactly the population the blind window touches.
  * the feed is 7 days deep, so a day whose deals have aged out contributes no
    rollover evidence; those days are counted as `no_feed_data`, not as normal.
  * the kill switch WRITES state when it halts. Every probe runs under a
    throwaway HERMES_DATA_ROOT (engines/paths seam) and a fresh state file per
    probe, so production kill_switch_state.json is never touched.

Read-only w.r.t. trading: one bridge history call (get_history_deals), no order
endpoint, no state file outside a temp dir. Post-processing is a PURE function
of the embedded rows (b127/b128), registered in scripts/b127_producer_reproduction.py.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(str(_ROOT / ".env"))

from engines import paths                                          # noqa: E402
from engines.defcon import classify_exits, compute_insights        # noqa: E402
from engines.kill_switch import check_kill_switch                  # noqa: E402
from engines.risk import assess_account_policy, compute_performance_state  # noqa: E402

LEDGER = _ROOT / "data" / "backtest" / "b141_rollover_blind_window_census.json"
FEED_DAYS = 7            # the same depth hermes_runtime._load_closed_trades asks for


# ── the three consumers, called the way production calls them ───────────────

def _regime(state: dict, balance: float) -> dict:
    """assess_account_policy with the deal-derived inputs from `state` and the
    drawdown legs neutralised (see module docstring)."""
    pol = assess_account_policy(
        balance=balance, equity=balance, free_margin=balance, margin=0.0,
        daily_pnl=float(state.get("daily_pnl", 0) or 0),
        loss_streak=int(state.get("loss_streak", 0) or 0),
        open_positions=0)
    return {"regime": pol.get("regime"),
            "trade_allowed": pol.get("trade_allowed"),
            "risk_multiplier": pol.get("risk_multiplier")}


def _defcon(state: dict, balance: float) -> dict:
    ins = compute_insights(
        loss_streak=int(state.get("loss_streak", 0) or 0),
        daily_pnl=float(state.get("daily_pnl", 0) or 0),
        balance=balance,
        classified=classify_exits(state.get("recent_closed") or []))
    return {"defcon": ins.get("defcon"),
            "risk_override": ins.get("risk_override"),
            "trade_allowed": ins.get("trade_allowed")}


def _kill(state: dict, balance: float, at: datetime) -> dict:
    """check_kill_switch on a THROWAWAY state file (it writes when it halts)."""
    tmp = Path(tempfile.mkdtemp(prefix="b141kill_"))
    (tmp / "data" / "xau_plan").mkdir(parents=True, exist_ok=True)
    old = os.environ.get("HERMES_DATA_ROOT")
    os.environ["HERMES_DATA_ROOT"] = str(tmp)
    paths.set_data_root(tmp)
    try:
        r = check_kill_switch(
            balance=balance, equity=balance,
            daily_pnl=float(state.get("daily_pnl", 0) or 0),
            consecutive_losses=int(state.get("loss_streak", 0) or 0),
            margin_free=balance, margin=0.0, now=at)
        return {"halted": bool(r.get("halted")), "reason": r.get("reason")}
    finally:
        if old is None:
            os.environ.pop("HERMES_DATA_ROOT", None)
        else:
            os.environ["HERMES_DATA_ROOT"] = old
        paths.set_data_root(None)


def consumers(state: dict, balance: float, at: datetime) -> dict:
    return {"policy": _regime(state, balance),
            "defcon": _defcon(state, balance),
            "kill": _kill(state, balance, at)}


# ── replay: reproduce the live loop day by day from the real feed ────────────

def _utc_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()


def _first_cycle_time(day: str) -> datetime:
    """The rollover cycle's wall clock: 00:00 UTC of `day`. The plan lane's real
    first tick is the 00:00 cron (15-min cadence); the signal lane polls every
    2s, so its blind window is seconds wide — the census measures the STATE, and
    the window width is reported separately from the feed's own timestamps."""
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _views(steady: dict, cold: dict, balance: float, at: datetime) -> dict:
    """The four readings of ONE boundary, all through the real consumers."""
    opt_a = dict(cold)
    opt_a["daily_pnl"] = float(steady.get("daily_pnl", 0) or 0)
    opt_a["loss_streak"] = int(steady.get("loss_streak", 0) or 0)
    opt_b = dict(cold)
    opt_b["cold_start"] = True
    return {
        "steady": consumers(steady, balance, at),
        "cold": consumers(cold, balance, at),
        "option_a": consumers(opt_a, balance, at),
        "option_b": consumers(opt_b, balance, at),
    }


def derive(deals: list[dict], balance: float) -> dict:
    """PURE function of (deals, balance) — b127/b128: re-derivable from the
    artifact's own embedded inputs.

    Walks the feed chronologically, day by day, carrying the state exactly the
    way the 15-minute loop does (one ROLLOVER cycle at midnight, then same-day
    cycles that fold the day's deals), and at every day boundary compares:

      steady   = what the LAST cycle of day D saw (day == D, full history)
      cold     = what the FIRST cycle of D+1 sees today (the rollover branch)
      opt_a    = the same cycle if daily_pnl/loss_streak were carried
      opt_b    = the same cycle with zeros + a cold flag (regime/DEFCON carried
                 through the flag, kill switch NOT)
    """
    deals = sorted((d for d in (deals or []) if d.get("time") is not None),
                   key=lambda d: (float(d["time"]), int(d.get("ticket") or 0)))
    days = sorted({_utc_day(float(d["time"])) for d in deals})
    rows = []
    end_state: dict = {}          # what the last cycle of the previous day held
    for day in days:
        through_prev = [d for d in deals if _utc_day(float(d["time"])) < day]
        through_day = [d for d in deals if _utc_day(float(d["time"])) <= day]

        steady = dict(end_state)
        cold = compute_performance_state(steady, day, balance, through_prev)
        # the day's own last cycle: same-day branch folds every deal of `day`
        end_state = compute_performance_state(cold, day, balance, through_day)
        if not through_prev:
            continue              # first day in the feed: no yesterday to compare
        rows.append({
            "rollover_day": day,
            "prev_day": days[days.index(day) - 1],
            **_views(steady, cold, balance, _first_cycle_time(day)),
            "steady_daily_pnl": steady.get("daily_pnl"),
            "steady_loss_streak": steady.get("loss_streak"),
            "cold_daily_pnl": cold.get("daily_pnl"),
            "cold_loss_streak": cold.get("loss_streak"),
            "cold_window_deals": len(cold.get("recent_closed") or []),
            "cycle2_daily_pnl": end_state.get("daily_pnl"),
            "cycle2_regime": _regime(end_state, balance)["regime"],
        })

    blind = [r for r in rows if r["cold"]["policy"]["regime"]
             != r["steady"]["policy"]["regime"]]
    a_halts = [r for r in rows if r["option_a"]["kill"]["halted"]
               and not r["cold"]["kill"]["halted"]]
    b_halts = [r for r in rows if r["option_b"]["kill"]["halted"]
               and not r["cold"]["kill"]["halted"]]
    a_flips = [r for r in blind if r["option_a"]["policy"]["regime"]
               == r["steady"]["policy"]["regime"]]
    a_defcon_flips = [r for r in blind
                      if r["option_a"]["defcon"]["defcon"] == r["steady"]["defcon"]["defcon"]]
    return {
        "n_boundaries": len(rows),
        "n_days_in_feed": len(days),
        "blind_regime_boundaries": [r["rollover_day"] for r in blind],
        "blind_count": len(blind),
        "option_a_restores_steady_regime": len(a_flips),
        "option_a_restores_steady_defcon": len(a_defcon_flips),
        "option_a_arms_kill_switch_that_cold_did_not": [
            {"day": r["rollover_day"], "reason": r["option_a"]["kill"]["reason"],
             "steady_daily_pnl": r["steady_daily_pnl"]} for r in a_halts],
        "option_b_arms_kill_switch_that_cold_did_not": [
            {"day": r["rollover_day"], "reason": r["option_b"]["kill"]["reason"]}
            for r in b_halts],
        "rows": rows,
    }


# ── synthetic threshold scan: the live feed has no losing day, so the price of
#    each option must be measured at the thresholds themselves, not at whatever
#    the last 7 days happened to look like. LABELLED SYNTHETIC on every row. ───

def _loss_day_deals(total: float, n: int, base_ts: float) -> list[dict]:
    """n closing deals summing to `total` profit, in the shape the feed returns."""
    each = round(total / n, 2)
    out = []
    for i in range(n):
        out.append({"ticket": 900001 + i, "time": base_ts - 600 * (i + 1),
                    "profit": each, "entry": 1, "comment": "[sl 4460.0]",
                    "symbol": "XAUUSD", "position_id": 900001 + i})
    return out


# risk.py's own daily-loss legs, read out of its source (b109: never restate a
# literal — if the rule moves, the scan moves with it).
def _risk_daily_loss_legs() -> list[float]:
    import re
    import engines.risk as RISK
    src = Path(RISK.__file__).read_text(encoding="utf-8")
    return sorted({float(m) for m in
                   re.findall(r"daily_pnl <= -\(balance \* ([\d.]+)\)", src)})


def _kill_daily_loss_leg() -> float:
    import engines.kill_switch as KS
    return float(KS.DAILY_LOSS_LIMIT_PCT)


def synthetic_arms(balance: float) -> dict:
    """The live feed has no losing day, so the PRICE of each fix option has to be
    measured at the thresholds themselves, not at whatever the last 7 days looked
    like. Sweep yesterday's loss from 0 to 1.4x the kill-switch threshold and
    record, per step, what each consumer sees under steady / cold / option_a /
    option_b. LABELLED SYNTHETIC.

    Arms are CHECKED to be the rule they are named for (b122): each row carries
    the daily_pnl the state actually handed the consumers.
    """
    now = datetime(2026, 9, 8, 0, 0, 0, tzinfo=timezone.utc)
    legs = _risk_daily_loss_legs() + [_kill_daily_loss_leg()]
    top = max(legs) * 1.4
    steps = 28
    rows = []
    for k in range(1, steps + 1):
        frac = top * k / steps
        total = -round(balance * frac, 2)
        deals = _loss_day_deals(total, 2, now.timestamp())
        steady = compute_performance_state({"day": "2026-09-07"}, "2026-09-07",
                                           balance, deals)
        cold = compute_performance_state(steady, "2026-09-08", balance, deals)
        v = _views(steady, cold, balance, now)
        rows.append({
            "synthetic": True,
            "yesterday_loss_pct_of_balance": round(frac, 4),
            "yesterday_loss_usd": total,
            "legs_crossed": [x for x in legs if frac >= x],
            "steady_daily_pnl": steady.get("daily_pnl"),
            "steady_loss_streak": steady.get("loss_streak"),
            "cold_daily_pnl": cold.get("daily_pnl"),
            **v,
        })
    # a losing STREAK arm (2 straight small losses): the leg that makes risk.py
    # say defensive AND defcon YELLOW at the same time (b137's double-charge),
    # which the rollover also erases.
    deals = _loss_day_deals(-round(balance * 0.004, 2), 2, now.timestamp())
    steady = compute_performance_state({"day": "2026-09-07"}, "2026-09-07",
                                       balance, deals)
    cold = compute_performance_state(steady, "2026-09-08", balance, deals)
    streak = {"arm": "streak_only", "synthetic": True,
              "yesterday_loss_pct_of_balance": 0.004,
              "steady_loss_streak": steady.get("loss_streak"),
              "cold_loss_streak": cold.get("loss_streak"),
              **_views(steady, cold, balance, now)}

    return {
        "note": ("synthetic sweep: yesterday's realised loss as a fraction of "
                 "balance, replayed through the real consumers at a UTC "
                 "midnight rollover. Not observed history."),
        "risk_daily_loss_legs_pct": _risk_daily_loss_legs(),
        "kill_daily_loss_leg_pct": _kill_daily_loss_leg(),
        "rows": rows,
        "streak_arm": streak,
        "regime_blind_loss_pcts": [r["yesterday_loss_pct_of_balance"] for r in rows
                                   if r["cold"]["policy"]["regime"]
                                   != r["steady"]["policy"]["regime"]],
        "defcon_blind_loss_pcts": [r["yesterday_loss_pct_of_balance"] for r in rows
                                   if r["cold"]["defcon"]["defcon"]
                                   != r["steady"]["defcon"]["defcon"]],
        "optA_regime_matches_steady": sum(1 for r in rows if r["option_a"]["policy"]["regime"]
                                          == r["steady"]["policy"]["regime"]),
        "optA_defcon_matches_steady": sum(1 for r in rows if r["option_a"]["defcon"]["defcon"]
                                          == r["steady"]["defcon"]["defcon"]),
        "optA_kill_halts": [r["yesterday_loss_pct_of_balance"] for r in rows
                            if r["option_a"]["kill"]["halted"]],
        "optB_kill_halts": [r["yesterday_loss_pct_of_balance"] for r in rows
                            if r["option_b"]["kill"]["halted"]],
        "optB_regime_matches_steady": sum(1 for r in rows if r["option_b"]["policy"]["regime"]
                                          == r["steady"]["policy"]["regime"]),
        "optB_defcon_matches_steady": sum(1 for r in rows if r["option_b"]["defcon"]["defcon"]
                                          == r["steady"]["defcon"]["defcon"]),
        "steady_kill_halts": [r["yesterday_loss_pct_of_balance"] for r in rows
                              if r["steady"]["kill"]["halted"]],
        "n_rows": len(rows),
    }




def verdict(derived: dict, thresholds: dict) -> str:
    """Named states (b135: a decision trigger is a CONJUNCTION, and both axes are
    reported separately, never OR'd into one escalation). The restore counts are
    measured OVER THE BLIND ROWS ONLY — a fix that agrees with steady on a
    boundary that was never blind proves nothing."""
    if derived["blind_count"] == 0:
        return "NO_BLIND_WINDOW_MEASURED"
    a_halts = derived["option_a_arms_kill_switch_that_cold_did_not"]
    if a_halts:
        return ("OPTION_A_IS_NOT_NEUTRAL: it arms the kill switch on "
                f"{len(a_halts)}/{derived['blind_count']} blind boundaries "
                f"(halt threshold {thresholds['daily_loss_pct']:.0%} of balance, "
                f"cooldown {thresholds['cooldown_hours']}h) — a human gate, not a side effect")
    if derived["option_a_restores_steady_regime"] == derived["blind_count"]:
        return ("OPTION_A_RESTORES_EVERY_BLIND_REGIME_AND_ARMS_NOTHING"
                f" ({derived['option_a_restores_steady_regime']}/"
                f"{derived['blind_count']} blind boundaries restored, "
                f"{derived['option_a_restores_steady_defcon']}/"
                f"{derived['blind_count']} DEFCON)")
    return "OPTION_A_PARTIAL"


def main() -> int:
    from bridge_client import BridgeClient
    bridge = BridgeClient()
    resp = bridge.get_history_deals("XAUUSD", FEED_DAYS) or {}
    deals = resp.get("data") or resp.get("deals") or []
    acct = bridge.get_account() or {}
    balance = float(acct.get("balance") or acct.get("data", {}).get("balance") or 0.0)
    if not deals or balance <= 0:
        print("NO FEED — census cannot run (bridge empty or balance unreadable)")
        return 2

    import engines.kill_switch as KS
    thresholds = {"daily_loss_pct": KS.DAILY_LOSS_LIMIT_PCT,
                  "cooldown_hours": KS.COOLDOWN_HOURS,
                  "consecutive_losses_limit": KS.CONSECUTIVE_LOSSES_LIMIT}

    derived = derive(deals, balance)
    scan = synthetic_arms(balance)
    out = {
        "_built_at": datetime.now(timezone.utc).isoformat(),
        "_note": ("b141: what the first cycle of each UTC day loses, measured "
                  "through the real compute_performance_state / "
                  "assess_account_policy / compute_insights / check_kill_switch "
                  "on the real 7-day deal feed, plus a SYNTHETIC threshold sweep "
                  "(the feed has no losing day). Prices the two fix options; "
                  "ships NEITHER. Read-only; kill-switch probes ran under a "
                  "throwaway data root."),
        "_thresholds": thresholds,
        "_balance_used": balance,
        "_feed_days": FEED_DAYS,
        "_deal_count": len(deals),
        "derived": derived,
        "synthetic_sweep": scan,
        "verdict": verdict(derived, thresholds),
        # b127/b128: embed the join inputs so the artifact re-derives alone
        "_deals_embedded": [
            {k: d.get(k) for k in ("ticket", "time", "profit", "entry",
                                   "comment", "position_id")}
            for d in sorted(deals, key=lambda x: float(x.get("time") or 0))],
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")

    print(f"feed: {len(deals)} deals over {derived['n_days_in_feed']} days, "
          f"balance {balance:.2f}")
    print(f"day boundaries measured: {derived['n_boundaries']}")
    print(f"blind regime boundaries: {derived['blind_count']} "
          f"{derived['blind_regime_boundaries']}")
    for r in derived["rows"]:
        print(f"  {r['rollover_day']}: steady={r['steady']['policy']['regime']}/"
              f"{r['steady']['defcon']['defcon']}/kill={r['steady']['kill']['halted']} "
              f"(pnl {r['steady_daily_pnl']}, streak {r['steady_loss_streak']}) -> "
              f"cold={r['cold']['policy']['regime']}/{r['cold']['defcon']['defcon']}/"
              f"kill={r['cold']['kill']['halted']} | optA={r['option_a']['policy']['regime']}/"
              f"{r['option_a']['defcon']['defcon']}/kill={r['option_a']['kill']['halted']} "
              f"({r['option_a']['kill']['reason']}) | optB kill={r['option_b']['kill']['halted']}")
    print("VERDICT:", out["verdict"])
    print("\nSYNTHETIC SWEEP (yesterday's loss % of balance -> regime/defcon/kill):")
    print(f"  risk.py daily-loss legs: {scan['risk_daily_loss_legs_pct']} | "
          f"kill_switch leg: {scan['kill_daily_loss_leg_pct']}")
    prev = None
    for r in scan["rows"]:
        sig = (r["steady"]["policy"]["regime"], r["steady"]["defcon"]["defcon"],
               r["steady"]["kill"]["halted"], r["cold"]["policy"]["regime"],
               r["cold"]["defcon"]["defcon"], r["cold"]["kill"]["halted"],
               r["option_a"]["policy"]["regime"], r["option_a"]["defcon"]["defcon"],
               r["option_a"]["kill"]["halted"], r["option_b"]["kill"]["halted"])
        if sig != prev:
            print(f"  {r['yesterday_loss_pct_of_balance']:>6.2%}: "
                  f"steady={r['steady']['policy']['regime']}/{r['steady']['defcon']['defcon']}"
                  f"/kill={r['steady']['kill']['halted']}  "
                  f"cold={r['cold']['policy']['regime']}/{r['cold']['defcon']['defcon']}"
                  f"/kill={r['cold']['kill']['halted']}  "
                  f"A={r['option_a']['policy']['regime']}/{r['option_a']['defcon']['defcon']}"
                  f"/kill={r['option_a']['kill']['halted']}  "
                  f"B=kill={r['option_b']['kill']['halted']}")
            prev = sig
    sa = scan["streak_arm"]
    print(f"  streak arm (2 small losses, {sa['yesterday_loss_pct_of_balance']:.2%}): "
          f"steady streak={sa['steady_loss_streak']} -> cold streak={sa['cold_loss_streak']}, "
          f"steady={sa['steady']['policy']['regime']}/{sa['steady']['defcon']['defcon']} "
          f"cold={sa['cold']['policy']['regime']}/{sa['cold']['defcon']['defcon']}")
    print(f"  blind regime steps: {len(scan['regime_blind_loss_pcts'])}/{scan['n_rows']} "
          f"(from {min(scan['regime_blind_loss_pcts'], default=0):.2%})")
    print(f"  blind defcon steps: {len(scan['defcon_blind_loss_pcts'])}/{scan['n_rows']}")
    print(f"  option_a restores steady regime on {scan['optA_regime_matches_steady']}/"
          f"{scan['n_rows']}, defcon on {scan['optA_defcon_matches_steady']}/{scan['n_rows']}")
    print(f"  option_b restores steady regime on {scan['optB_regime_matches_steady']}/"
          f"{scan['n_rows']}, defcon on {scan['optB_defcon_matches_steady']}/{scan['n_rows']}")
    print(f"  kill halts: steady at {scan['steady_kill_halts']}, "
          f"option_a at {scan['optA_kill_halts']}, option_b at {scan['optB_kill_halts']}")
    print("ledger:", LEDGER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
