#!/usr/bin/env python3
"""b137 — SHRINK-STACK CENSUS: how many independent factors multiply into one
risk_pct, what their COMBINED floor is, and whether that floor kills the lane.

This is b136's procedure applied to the next un-censused pair, named in b136's
own ledger. `engines/auto_executor.evaluate_proposal` builds its entry size as

    risk_pct = MAX_RISK_PER_TRADE_PCT
             * learning.risk_mult      (engines/learning.py, tighten-only)
             * STYLE_RISK_MULT[style]  (b53, per execution_style)
             * defcon.risk_override    (YELLOW -> 0.5)
             * 0.5 if regime in TIGHT_REGIMES

Four modules that never see each other, each believing it is THE risk damper.
No test pinned the COMBINED product. Three questions, answered by RUNNING the
real code (b136/b109: never restate a literal you can probe):

  Q1 RANGE — what values can each factor actually take? Discovered by calling
     the real emitter over branch-hitting probes: learning's floor comes out of
     `learning.apply()` under a redirected data root, DEFCON's overrides out of
     `compute_insights()`, the TIGHT_REGIMES multiplier out of the OBSERVABLE
     risk_pct of a real `evaluate_proposal()` call (divided by the static cap),
     and the style keys out of an AST scan of the styles `engines/plan.py` can
     EMIT cross-checked against STYLE_RISK_MULT.

  Q2 MOVEMENT — does each factor actually move the lot? Feed every combination
     through the REAL evaluate_proposal and record risk_pct AND lot. A factor
     that does not move the observable is unwired (the b136 bug class).

  Q3 EXPOSURE — how often does the stack reach its floor on the real books, and
     is the lane still alive there? Replays the trade journal through the real
     state chain to get the regime + DEFCON each historical moment would have
     produced, then asks, for the stop distances the system ACTUALLY traded
     (execution_log), whether the floored risk_pct still yields a lot at or
     above the broker minimum. A permanently-too-small lane is dead code that
     looks alive: sizing_below_min_meaningful_lot is a silent skip, not an alarm.

UNPLANNED FINDING (see _derived.double_count): `loss_streak >= 2` is the trigger
for TWO independent dampers at once — engines/risk.assess_account_policy calls it
"defensive" (executor x0.5) and engines/defcon.compute_insights calls it YELLOW
(executor x0.5). One observable fact is therefore charged 0.25x. Proving it is
cheap; REMOVING one leg would LOOSEN the gate, which the autopilot may never do,
so it is measured, pinned and filed as a human decision (b138).

Read-only: no bridge, no order endpoint, no production state. The learning-floor
probe runs against a throwaway HERMES_DATA_ROOT. Post-processing is a PURE
function of the collected rows (b127/b128) so scripts/b127_producer_reproduction
.py can re-execute it against the frozen ledger.
"""
from __future__ import annotations

import ast
import csv
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

from engines import auto_executor as AE                        # noqa: E402
from engines import cooldown as CD                             # noqa: E402
from engines import learning as L                              # noqa: E402
from engines import risk as RISK                               # noqa: E402
from engines.defcon import classify_exits, compute_insights    # noqa: E402
from engines.risk import assess_account_policy, compute_performance_state  # noqa: E402

LEDGER = _ROOT / "data" / "backtest" / "b137_shrink_stack_census.json"
JOURNAL = _ROOT / "data" / "xau_plan" / "trade_journal.csv"
EXEC_LOG = _ROOT / "data" / "xau_plan" / "execution_log.csv"

# A neutral, gate-passing SELL: 10.00 stop, 25.00 target (RR 2.5) — the same
# blueprint b136 uses, so the two censuses describe one geometry.
BLUEPRINT = {"side": "SELL", "entry_price": 4450.0, "sl": 4460.0,
             "tp": 4425.0, "symbol": "XAUUSD"}
BALANCE = 5000.0


# ── Q1: discover each factor's range from its own emitter ─────────────────

def discover_learning_floor() -> dict:
    """learning's real clamp range, read out of the module's own functions.

    Runs under a throwaway data root so nothing in production is touched. The
    FLOOR is discoverable by asking apply() to clamp something below it. The
    CEILING is not: apply() is tighten-only (`min(proposed, current)`), so no
    apply() call can ever raise risk — the honest ceiling is the default state
    a fresh install starts from. Probing apply(5.0) would return whatever the
    previous probe wrote and read as a bogus ceiling, so it is not done.
    """
    tmp = Path(tempfile.mkdtemp(prefix="b137_"))
    (tmp / "data" / "xau_plan").mkdir(parents=True, exist_ok=True)
    old = os.environ.get("HERMES_DATA_ROOT")
    os.environ["HERMES_DATA_ROOT"] = str(tmp)
    try:
        ceiling = float(L.load_learning_state().get("risk_mult"))   # no file yet
        floor = float(L.apply({"risk_mult": 0.0}).get("risk_mult"))
    finally:
        if old is None:
            os.environ.pop("HERMES_DATA_ROOT", None)
        else:
            os.environ["HERMES_DATA_ROOT"] = old
    return {"floor": floor, "ceiling": ceiling, "tighten_only": True,
            "source": "engines.learning.load_learning_state()/apply() under a "
                      "temp data root"}


def discover_defcon_overrides() -> dict:
    """risk_override per DEFCON level, discovered from compute_insights probes."""
    probes = {
        # GREEN: empty window, no streak, flat day.
        "green": dict(loss_streak=0, daily_pnl=0.0, classified=[]),
        # YELLOW via loss_streak (the leg that ALSO makes risk.py say defensive).
        "yellow_streak": dict(loss_streak=2, daily_pnl=0.0, classified=[]),
        # YELLOW via an SL-dominated window (does NOT need a streak).
        "yellow_sldom": dict(loss_streak=0, daily_pnl=-1.0, classified=[
            {"exit_type": "sl", "profit": -5.0, "ticket": 1, "side": "buy"},
            {"exit_type": "sl", "profit": -5.0, "ticket": 2, "side": "buy"},
            {"exit_type": "sl", "profit": -5.0, "ticket": 3, "side": "buy"}]),
        # RED: >=5 deals, SL-dominant, losing day.
        "red": dict(loss_streak=0, daily_pnl=-100.0, classified=[
            {"exit_type": "sl", "profit": -5.0, "ticket": i, "side": "buy"}
            for i in range(1, 6)]),
    }
    out = {}
    for name, kw in probes.items():
        ins = compute_insights(balance=BALANCE, **kw)
        out[name] = {"defcon": ins.get("defcon"),
                     "risk_override": ins.get("risk_override"),
                     "trade_allowed": ins.get("trade_allowed")}
    return out


def discover_regime_multipliers() -> dict:
    """regime -> the multiplier the ENTRY PATH actually applies, measured off
    evaluate_proposal's own risk_pct (never off risk.py's risk_multiplier field,
    which b136 proved the executor does not read)."""
    probes = {
        "normal":    dict(daily_pnl=0.0, loss_streak=0, dd=0.0),
        # defensive via the DAILY-LOSS leg only — chosen so DEFCON stays GREEN
        # and the regime effect is measured alone (the streak leg is the
        # double-count probe, see regime_via_streak).
        "defensive": dict(daily_pnl=-BALANCE * 0.011, loss_streak=0, dd=0.0),
        "recovery":  dict(daily_pnl=0.0, loss_streak=0, dd=0.026),
        "locked":    dict(daily_pnl=0.0, loss_streak=0, dd=0.051),
        # defensive via loss_streak >= 2 — the SAME fact that turns DEFCON
        # YELLOW, so this probe measures the stacked charge.
        "defensive_via_streak": dict(daily_pnl=0.0, loss_streak=2, dd=0.0),
    }
    out = {}
    for name, p in probes.items():
        pol = assess_account_policy(balance=BALANCE,
                                    equity=round(BALANCE * (1 - p["dd"]), 2),
                                    free_margin=BALANCE, margin=0.0,
                                    daily_pnl=p["daily_pnl"],
                                    loss_streak=p["loss_streak"],
                                    open_positions=0)
        out[name] = {"regime": pol["regime"],
                     "policy_risk_multiplier": pol["risk_multiplier"],
                     # MEASURED off evaluate_proposal's own risk_pct (b136: the
                     # policy field is not what the entry path applies), with the
                     # style leg held at 1.0 and learning at neutral.
                     "measured_entry_mult": measured_entry_mult(pol["regime"]),
                     "trade_allowed": pol["trade_allowed"],
                     "probe": {"daily_pnl": p["daily_pnl"],
                               "loss_streak": p["loss_streak"],
                               "drawdown_pct": p["dd"]}}
    return out


def measured_entry_mult(regime: str, learning_mult: float = 1.0) -> float:
    """The multiplier the ENTRY PATH really applies for a regime: one real
    evaluate_proposal with only that regime's inputs set, divided by the base.
    Returns 1.0 if the probe cannot be taken (import-time guard)."""
    probe = {"normal": dict(daily_pnl=0.0, loss_streak=0, dd=0.0),
             "defensive": dict(daily_pnl=-BALANCE * 0.011, loss_streak=0, dd=0.0),
             "recovery": dict(daily_pnl=0.0, loss_streak=0, dd=0.026),
             "locked": dict(daily_pnl=0.0, loss_streak=0, dd=0.051)}
    if regime not in probe:
        return 1.0
    base = _proposal_result("", probe["normal"], 1.0)
    hit = _proposal_result("", probe[regime], learning_mult)
    if not base.get("risk_pct") or not hit.get("risk_pct"):
        return 1.0
    return round(float(hit["risk_pct"]) / float(base["risk_pct"]), 6)


def styles_plan_can_emit() -> list[str]:
    """Every execution_style literal engines/plan.py can produce (AST, b122:
    an arm must be the rule it is named for, not a hand-typed list)."""
    from engines import plan as PLAN
    src = Path(PLAN.__file__).read_text(encoding="utf-8")
    found: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Dict)):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "execution_style"
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str)
                        and v.value not in found):
                    found.append(v.value)
    return sorted(found)


def style_coverage() -> dict:
    emitted = styles_plan_can_emit()
    tagged = sorted(AE.STYLE_RISK_MULT)
    return {"styles_emitted_by_plan": emitted,
            "styles_with_a_risk_mult": tagged,
            "styles_at_full_risk": sorted(set(emitted) - set(tagged)),
            "tagged_styles_the_plan_never_emits": sorted(set(tagged) - set(emitted)),
            "min_style_mult": min(AE.STYLE_RISK_MULT.values())
            if AE.STYLE_RISK_MULT else 1.0}


# ── Q2: feed every combination through the REAL entry path ────────────────

def _proposal_result(style: str, regime_probe: dict, learning_mult: float,
                     classified: list[dict] | None = None) -> dict:
    """One real evaluate_proposal. Time gates stubbed OPEN (they are not the
    subject); learning is redirected through HERMES_DATA_ROOT, not monkeypatched,
    so the module's own clamp/merge path runs. Nothing reaches execute_trade."""
    real_open, real_cd = AE.is_market_open, CD.check_entry_cooldown
    AE.is_market_open = lambda *a, **k: True
    CD.check_entry_cooldown = lambda now=None: {"allowed": True}
    tmp = Path(tempfile.mkdtemp(prefix="b137_p_"))
    (tmp / "data" / "xau_plan").mkdir(parents=True, exist_ok=True)
    (tmp / "data" / "xau_plan" / "learning_state.json").write_text(
        json.dumps({"min_rr": 1.5, "min_grade": "B",
                    "risk_mult": learning_mult}), encoding="utf-8")
    old = os.environ.get("HERMES_DATA_ROOT")
    os.environ["HERMES_DATA_ROOT"] = str(tmp)
    try:
        pol = assess_account_policy(
            balance=BALANCE,
            equity=round(BALANCE * (1 - regime_probe["dd"]), 2),
            free_margin=BALANCE, margin=0.0,
            daily_pnl=regime_probe["daily_pnl"],
            loss_streak=regime_probe["loss_streak"],
            open_positions=0)
        day = datetime.now(timezone.utc).date().isoformat()
        perf = compute_performance_state({}, day, BALANCE, [])
        perf["loss_streak"] = int(regime_probe["loss_streak"])
        perf["daily_pnl"] = float(regime_probe["daily_pnl"])
        if classified:
            perf["recent_closed"] = classified
        res = AE.evaluate_proposal(
            {"blueprint": dict(BLUEPRINT), "grade": "B",
             "execution_style": style}, pol, perf, {}, None)
        ins = compute_insights(loss_streak=int(regime_probe["loss_streak"]),
                              daily_pnl=float(regime_probe["daily_pnl"]),
                              balance=BALANCE,
                              classified=classify_exits(classified or []))
    finally:
        AE.is_market_open = real_open
        CD.check_entry_cooldown = real_cd
        if old is None:
            os.environ.pop("HERMES_DATA_ROOT", None)
        else:
            os.environ["HERMES_DATA_ROOT"] = old
    risk_pct = res.get("risk_pct")
    return {
        "style": style or "(untagged)",
        "regime": pol["regime"],
        "defcon": ins.get("defcon"),
        "learning_mult": learning_mult,
        "execute": bool(res.get("execute")),
        "reason": res.get("reason"),
        "risk_pct": risk_pct,
        "combined_factor": (round(float(risk_pct) / AE.MAX_RISK_PER_TRADE_PCT, 6)
                            if risk_pct else None),
        "risk_usd": res.get("risk_usd"),
        "lot": (res.get("command") or {}).get("lot"),
    }


SLDOM = [{"ticket": i, "profit": -5.0, "comment": "[sl 4400]", "side": "sell",
          "entry": 1, "time": 0.0} for i in range(1, 4)]

PROBE_GRID: list[tuple[str, dict, float, list[dict] | None, str]] = [
    # (label, regime probe, learning_mult, extra closed deals, why)
    ("base_normal", dict(daily_pnl=0.0, loss_streak=0, dd=0.0), 1.0, None,
     "the reference: no damper fires"),
    ("tight_defensive_dailyloss", dict(daily_pnl=-BALANCE * 0.011,
                                       loss_streak=0, dd=0.0), 1.0, None,
     "regime leg alone (DEFCON stays GREEN)"),
    ("tight_defensive_streak", dict(daily_pnl=0.0, loss_streak=2, dd=0.0), 1.0,
     None, "regime leg fired BY loss_streak — DEFCON YELLOW fires on the same fact"),
    ("defcon_yellow_sldom", dict(daily_pnl=0.0, loss_streak=0, dd=0.0), 1.0,
     SLDOM, "DEFCON leg alone (regime stays normal)"),
    ("recovery", dict(daily_pnl=0.0, loss_streak=0, dd=0.026), 1.0, None,
     "the b136 regime"),
    ("style_half", dict(daily_pnl=0.0, loss_streak=0, dd=0.0), 1.0, None,
     "STYLE_RISK_MULT leg alone"),
    ("learning_floor", dict(daily_pnl=0.0, loss_streak=0, dd=0.0), 0.0, None,
     "learning leg at its clamped floor (0.0 is clamped up by apply())"),
    ("stack_all", dict(daily_pnl=0.0, loss_streak=2, dd=0.0), 0.0, SLDOM,
     "every damper at once: streak-defensive + YELLOW + style + learning floor"),
    ("locked", dict(daily_pnl=0.0, loss_streak=0, dd=0.051), 1.0, None,
     "the blocking regime"),
]


def size_grid() -> list[dict]:
    floor = discover_learning_floor()["floor"]
    rows = []
    for label, probe, lm, extra, why in PROBE_GRID:
        # the style leg rides on the probes that name it, and on stack_all
        # (which claims EVERY damper at once).
        style = ("aggressive_value_entry"
                 if label.startswith("style") or label == "stack_all" else "")
        if label in ("learning_floor", "stack_all"):
            # the honest worst case is the CLAMPED floor, not an arbitrary 0:
            # learning.apply() can never write below it, so the stack cannot
            # either. Probing 0.0 would invent a state the module forbids.
            lm = floor
        r = _proposal_result(style, probe, lm, extra)
        r["probe"] = label
        r["why"] = why
        rows.append(r)
    return rows


# ── Q3: exposure on the real books ────────────────────────────────────────

def _journal_rows() -> list[dict]:
    if not JOURNAL.exists():
        return []
    out = []
    with JOURNAL.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out.append({"ticket": int(float(r["ticket"])),
                            "time": float(r["close_time"]),
                            "profit": float(r["profit"]),
                            "comment": r.get("comment") or "",
                            "entry": 1})
            except (KeyError, TypeError, ValueError):
                continue
    return sorted(out, key=lambda d: d["ticket"])


def _stop_distances() -> list[float]:
    """The stop distances the system ACTUALLY traded — the geometry the floor
    has to survive, taken from the execution log rather than assumed."""
    if not EXEC_LOG.exists():
        return []
    out = []
    with EXEC_LOG.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out.append(abs(float(r["entry"]) - float(r["sl"])))
            except (KeyError, TypeError, ValueError):
                continue
    return sorted(out)


def history_walk(start_balance: float = BALANCE) -> list[dict]:
    """Replay the journal through the real chain and record the SHRINK STACK
    each historical moment would have applied (style excluded: it is not
    persisted — see the b139 observability finding)."""
    floor = discover_learning_floor()["floor"]
    rows, bal, state = [], float(start_balance), {}
    for d in _journal_rows():
        bal = round(bal + d["profit"], 2)
        day = datetime.fromtimestamp(d["time"], tz=timezone.utc).date().isoformat()
        state = compute_performance_state(state, day, bal, [d])
        pol = assess_account_policy(balance=bal, equity=bal, free_margin=bal,
                                    margin=0.0,
                                    daily_pnl=float(state.get("daily_pnl") or 0.0),
                                    loss_streak=int(state.get("loss_streak") or 0),
                                    open_positions=0)
        ins = compute_insights(
            loss_streak=int(state.get("loss_streak") or 0),
            daily_pnl=float(state.get("daily_pnl") or 0.0), balance=bal,
            classified=classify_exits(state.get("recent_closed") or []))
        tight = 0.5 if pol["regime"] in AE.TIGHT_REGIMES else 1.0
        override = ins.get("risk_override")
        override = 1.0 if override is None else float(override)
        rows.append({
            "deal_ticket": d["ticket"], "day": day, "balance": bal,
            "loss_streak": int(state.get("loss_streak") or 0),
            "daily_pnl": float(state.get("daily_pnl") or 0.0),
            "regime": pol["regime"], "defcon": ins.get("defcon"),
            "tight_mult": tight, "defcon_mult": override,
            "stack_as_shipped": round(tight * override, 6),
            "stack_with_learning_floor": round(tight * override * floor, 6),
            "stack_with_style": round(tight * override * floor * 0.5, 6),
        })
    return rows


# ── pure post-processing (b128: reachable from a test) ────────────────────

def lot_for(risk_pct: float, balance: float, stop: float) -> float:
    """The broker lot a risk_pct buys at a given stop distance, through the
    REAL sizing function (orchestrator) so the floor test is arithmetic on the
    same code the entry path runs, not a re-derived formula."""
    from engines.orchestrator import compute_xau_position_size
    s = compute_xau_position_size(balance=balance, risk_pct=risk_pct,
                                  stop_distance_price=stop, point=0.01,
                                  point_value_per_lot=1.0, volume_min=0.01,
                                  volume_step=0.01, volume_max=1.0,
                                  min_meaningful_lot=0.01)
    return float(s.get("lot") or 0.0)


def derive(grid: list[dict], hist: list[dict], stops: list[float],
           learning: dict, styles: dict, defcon: dict,
           regimes: dict, balance: float = BALANCE) -> dict:
    """The verdict, as a pure function of the collected rows."""
    by_probe = {r["probe"]: r for r in grid}
    base = by_probe["base_normal"]["combined_factor"]

    def factor(name):
        r = by_probe.get(name) or {}
        return r.get("combined_factor")

    # every factor must actually MOVE the lot (b136's wiring test, per leg)
    movement = {}
    for name in ("tight_defensive_dailyloss", "defcon_yellow_sldom",
                 "style_half", "learning_floor", "recovery",
                 "tight_defensive_streak"):
        f = factor(name)
        movement[name] = {
            "combined_factor": f,
            "moved": (f is not None and abs(f - base) > 1e-9),
            "lot": (by_probe.get(name) or {}).get("lot"),
            "executed": (by_probe.get(name) or {}).get("execute"),
        }

    # the double-count: one fact (loss_streak >= 2) charged by two modules
    daily_only = factor("tight_defensive_dailyloss")
    by_streak = factor("tight_defensive_streak")
    yellow_only = factor("defcon_yellow_sldom")
    double_count = {
        "fact": "loss_streak >= 2",
        "regime_leg_alone": daily_only,          # defensive via daily loss
        "defcon_leg_alone": yellow_only,         # YELLOW via SL-dominance
        "both_legs_via_streak": by_streak,       # one fact, both dampers
        "product_of_the_two_legs": (round(daily_only * yellow_only, 6)
                                    if daily_only and yellow_only else None),
        "is_double_counted": (by_streak is not None
                              and daily_only is not None
                              and yellow_only is not None
                              and abs(by_streak - daily_only * yellow_only) < 1e-9
                              and by_streak < min(daily_only, yellow_only)),
    }

    # the floor and whether the lane survives it. The floor is the PRODUCT of
    # the discovered minimum of every damper (not the probe's risk_pct, which is
    # None precisely BECAUSE the floor kills the sizing — that is the finding,
    # so it cannot also be the measurement).
    learning_floor = float(learning["floor"])
    min_style = float(styles["min_style_mult"])
    tight = min(float(v["measured_entry_mult"]) for v in regimes.values()
                if v["regime"] in AE.TIGHT_REGIMES)
    yellows = [float(v["risk_override"]) for v in defcon.values()
               if v["risk_override"] not in (None, 1.0)
               and v["trade_allowed"]]           # RED (0.0) blocks, never sizes
    min_defcon = min(yellows) if yellows else 1.0
    floor_factor = round(learning_floor * min_style * tight * min_defcon, 8)
    floor_risk_pct = round(AE.MAX_RISK_PER_TRADE_PCT * floor_factor, 8)
    stack_all = by_probe.get("stack_all") or {}
    alive = {}
    for stop in sorted(set([round(s, 2) for s in stops])):
        lot = lot_for(floor_risk_pct, balance, stop)
        alive[f"{stop:.2f}"] = {"lot_at_floor": lot, "lane_alive": lot >= 0.01}
    med = stops[len(stops) // 2] if stops else None
    dead_stops = [k for k, v in alive.items() if not v["lane_alive"]]
    # the probe must AGREE with the arithmetic: the probe ran on BLUEPRINT
    # (stop distance 10.00), so the analytic lot at that same stop must reach
    # the same verdict as evaluate_proposal did. Two independent readings,
    # one truth.
    probe_says_dead = (not stack_all.get("execute")
                       and "sizing_below_min_meaningful_lot" in
                       str(stack_all.get("reason")))
    blueprint_stop = abs(BLUEPRINT["entry_price"] - BLUEPRINT["sl"])
    analytic_dead_at_10 = lot_for(floor_risk_pct, balance,
                                  blueprint_stop) < 0.01

    # exposure: how often the ACTUAL historical stack (the two legs live can
    # observe from the books) shrank the size, and how often BOTH shrank at once
    counts: dict[str, int] = {}
    both = 0
    for h in hist:
        counts[h["regime"]] = counts.get(h["regime"], 0) + 1
        if h["tight_mult"] < 1.0 and h["defcon_mult"] < 1.0:
            both += 1

    return {
        "factors_in_the_stack": {
            "static_cap_pct": AE.MAX_RISK_PER_TRADE_PCT,
            "learning_risk_mult": learning,
            "style_risk_mult": styles,
            "defcon_risk_override": defcon,
            "regime_tight": regimes,
            "n_independent_dampers": 4,
        },
        "movement": movement,
        "unwired_factors": sorted(k for k, v in movement.items() if not v["moved"]),
        "double_count": double_count,
        "floor": {
            "combined_factor_analytic": floor_factor,
            "risk_pct_analytic": floor_risk_pct,
            "stack_all_executed": stack_all.get("execute"),
            "stack_all_reason": stack_all.get("reason"),
            "probe_agrees_with_arithmetic": (probe_says_dead
                                             == analytic_dead_at_10),
            "median_traded_stop_distance": med,
            "lane_alive_at_median": bool(alive.get(f"{med:.2f}", {}).get("lane_alive"))
            if med is not None else None,
            "stops_where_lane_is_dead": sorted(dead_stops, key=float),
            "per_stop": alive,
        },
        "exposure": {
            "journal_samples": len(hist),
            "regime_fire_counts": counts,
            "samples_where_both_live_dampers_shrank": both,
            "style_leg_is_unmeasurable_from_history": True,
        },
        "verdict": _verdict(movement, double_count, floor_factor, alive, med),
    }


def _verdict(movement: dict, double_count: dict, floor_factor, alive: dict,
             med) -> dict:
    out = {}
    unwired = sorted(k for k, v in movement.items() if not v["moved"])
    out["unwired_factors"] = unwired or "NONE — every damper moves the lot"
    out["double_count"] = (
        f"loss_streak>=2 charges {double_count['both_legs_via_streak']}x "
        f"(regime {double_count['regime_leg_alone']}x x defcon "
        f"{double_count['defcon_leg_alone']}x) — one fact, two modules"
        if double_count["is_double_counted"] else "no overlap measured")
    if floor_factor and med is not None:
        lot = alive.get(f"{med:.2f}", {}).get("lot_at_floor")
        out["floor"] = (f"floor {floor_factor:.4f}x = "
                        f"{AE.MAX_RISK_PER_TRADE_PCT * floor_factor:.5f} risk_pct; "
                        f"at the median traded stop ({med:.2f}) that is lot "
                        f"{lot} -> lane "
                        f"{'ALIVE' if lot and lot >= 0.01 else 'DEAD (silent skip)'}")
    out["style_leg"] = ("execution_style is NOT persisted in execution_log or the "
                        "journal, so the only per-trade damper cannot be audited "
                        "from history (filed b139)")
    out["action"] = ("MEASURED, NOTHING WIRED: removing the double-count would "
                     "LOOSEN a risk gate (human decision, b138); the floor is a "
                     "skip not an alarm, so a deeper stack would silence the lane "
                     "quietly (b139 observability).")
    return out


def self_check(d: dict) -> list[str]:
    """Assertions ON THE LEDGER (b122: a census that cannot fail is a census
    that will silently rot). Returns problems; empty means the ledger is
    internally consistent and every leg is wired."""
    problems: list[str] = []
    f = d["factors_in_the_stack"]
    if f["n_independent_dampers"] != 4:
        problems.append(f"damper count moved: {f['n_independent_dampers']} != 4")
    if d["unwired_factors"]:
        problems.append(f"unwired damper(s): {d['unwired_factors']}")
    if not d["double_count"]["is_double_counted"]:
        problems.append("the loss_streak>=2 double-count stopped reproducing — "
                        "either it was fixed (retire this census) or the wiring "
                        "drifted; re-read before trusting the ledger")
    if not d["floor"]["probe_agrees_with_arithmetic"]:
        problems.append("probe vs arithmetic disagree on the floor lane")
    if f["learning_risk_mult"]["floor"] >= f["learning_risk_mult"]["ceiling"]:
        problems.append("learning floor >= ceiling — discovery broke")
    if f["style_risk_mult"]["tagged_styles_the_plan_never_emits"]:
        problems.append("STYLE_RISK_MULT tags a style plan.py never emits: "
                        + str(f["style_risk_mult"]
                              ["tagged_styles_the_plan_never_emits"]))
    if d["floor"]["lane_alive_at_median"]:
        problems.append("the floor lane came back ALIVE at the median stop — "
                        "something loosened; this census must be re-read, not "
                        "silently re-stamped")
    return problems


def main() -> dict:
    grid = size_grid()
    hist = history_walk()
    stops = _stop_distances()
    learning = discover_learning_floor()
    styles = style_coverage()
    defcon = discover_defcon_overrides()
    regimes = discover_regime_multipliers()
    return {
        "_note": "b137 census: every factor that multiplies into entry risk_pct, "
                 "probed through the real evaluate_proposal. Read-only; no order "
                 "endpoint touched; the learning probe writes to a temp root.",
        "_at": datetime.now(timezone.utc).isoformat(),
        "_frame": {
            "blueprint": BLUEPRINT, "balance": BALANCE,
            "static_cap_pct": AE.MAX_RISK_PER_TRADE_PCT,
            "min_meaningful_lot": 0.01,
            "journal_rows": len(_journal_rows()),
            "execution_log_stops": len(stops),
            "learning_floor_is_discovered_not_copied": True,
        },
        "grid": grid,
        "history": hist,
        "traded_stop_distances": [round(s, 2) for s in stops],
        "_derived": derive(grid, hist, stops, learning, styles, defcon, regimes),
    }


def build_ledger() -> dict:
    out = main()
    out["_self_check_problems"] = self_check(out["_derived"])
    return out


if __name__ == "__main__":
    out = build_ledger()
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(out, indent=1), encoding="utf-8")
    d = out["_derived"]
    print("factors:", list(d["factors_in_the_stack"]))
    print("unwired:", d["unwired_factors"])
    print("double count:", json.dumps(d["double_count"]))
    print("floor:", json.dumps({k: v for k, v in d["floor"].items()
                                if k != "per_stop"}))
    print("exposure:", json.dumps(d["exposure"]))
    for k, v in d["verdict"].items():
        print(f"  {k}: {v}")
    if out["_self_check_problems"]:
        print("SELF-CHECK PROBLEMS:")
        for p in out["_self_check_problems"]:
            print("  !", p)
    print("ledger:", LEDGER)
