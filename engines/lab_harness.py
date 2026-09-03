#!/usr/bin/env python3
"""b71 — the ONE lab measurement harness (fixes the round-6 measurement bug).

Why this exists (b68 round 6, todo b71): every lab script hand-rolled its own
`r_stats()` and called `backtest_ohlc` WITHOUT `time_stop_bars`, so arms were
scored under exit rules the live system will never give them. The round-6
level-anchored arm printed exp_R +1.096 — the best number any lab arm ever
produced — and it was an artefact: mean stop 5.66 ATR from entry, mean hold 87
M15 bars (max 520 = 5+ days). A swing position, scored on an intraday board.
Under the live 36h time_exit it collapses to +0.787R on n=41.

The second failure mode this closes (b69 class): an arm with broken stop
geometry (risk <= 0) drops every signal silently, and `trades: 0` reads as
"this method has no edge" when nothing was measured. Here a zero-trade row
must carry a named reason from `diagnose()`.

Three guarantees, enforced by `run_arm()` + `check_honesty()`:

1. Every arm is measured three ways — `plain` (fixed 2R), `ladder` (the live
   b60 exit ladder) and `ladder_ts` (that ladder PLUS the live time exit).
   exp_R may only be quoted from a row that has `ladder_ts`.
2. Every row carries hold statistics (mean/p95/max in bars, plus how many
   holds exceed the time exit), so a swing-shaped arm is visible as such.
3. A zero-trade row must name the clause that never fired.

The time-exit limit is DERIVED from the live guard
(`engines.legacy_guards.MAX_POSITION_AGE_HOURS`) and the dataset's own bar
spacing — never hardcoded — so an M5 round gets 432 bars and an M15 round gets
144, both the same 36 hours of live risk.

Read-only research code: nothing here is imported by the live trading path.
"""
from __future__ import annotations

import statistics
from typing import Callable

from engines.backtest import backtest_ohlc
from engines.legacy_guards import MAX_POSITION_AGE_HOURS
from engines.trade_management import _partial_close_fraction

# Live-parity measurement constants shared by every lab round.
SPREAD = 0.20                 # XAUUSD demo round-trip cost (live assumption)
MIN_RR = 0.0                  # lab arms measure raw expectancy; live gate 6
                              # belongs to the funnel, not to an arm
LADDER = dict(                # the live b60 exit ladder, verbatim
    partial_tp1_share=0.5,
    tp1_position=0.50,
    trail_after_partial=0.5,
    breakeven_at_r=0.0,
    partial_share_fn=lambda t: _partial_close_fraction(t),
)


# ── time exit ──────────────────────────────────────────────────────────────
def bar_seconds(rows: list[dict]) -> int:
    """Median spacing between bar timestamps (robust to the weekend gap)."""
    gaps = [int(rows[i + 1]["time"]) - int(rows[i]["time"])
            for i in range(len(rows) - 1)]
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        raise ValueError("cannot infer bar spacing from this dataset")
    return int(statistics.median(gaps))


def live_time_stop_bars(rows: list[dict]) -> int:
    """The live 36h time_exit expressed in THIS dataset's bar length."""
    return int(MAX_POSITION_AGE_HOURS * 3600 // bar_seconds(rows))


# ── statistics ─────────────────────────────────────────────────────────────
def r_stats(res: dict, time_stop_bars: int = 0) -> dict:
    """R-multiple stats PLUS hold statistics (b71: the hold column is mandatory).

    R = pnl / original risk, so an arm with an absurdly wide stop keeps an R
    that is NOT comparable to the funnel's ~1 ATR risk — which is exactly why
    mean_hold_bars sits next to exp_R and why `ladder_ts` exists at all.
    """
    rs: list[float] = []
    holds: list[int] = []
    for t in res.get("trade_log", []):
        risk = abs(float(t["entry"]) - float(t.get("orig_sl") or t["sl"])) or 1
        rs.append(float(t["pnl"]) / risk)
        holds.append(int(t["exit_index"]) - int(t["entry_index"]))
    if not rs:
        return {"trades": 0, "exp_R": None, "net_R": None, "maxDD_R": None,
                "mean_hold_bars": None, "p95_hold_bars": None,
                "max_hold_bars": None, "holds_over_time_exit": None}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = abs(sum(losses) / len(losses)) if losses else 0.001
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    hs = sorted(holds)
    return {"trades": len(rs),
            "exp_R": round(sum(rs) / len(rs), 3),
            "WR%": round(100 * len(wins) / len(rs), 1),
            "avg_win_R": round(avg_w, 2),
            "avg_loss_R": round(-avg_l, 2),
            "net_R": round(sum(rs), 1),
            "maxDD_R": round(dd, 1),
            "mean_hold_bars": round(sum(hs) / len(hs), 1),
            "p95_hold_bars": hs[int(0.95 * (len(hs) - 1))],
            "max_hold_bars": hs[-1],
            "holds_over_time_exit": (sum(1 for h in hs if h > time_stop_bars)
                                     if time_stop_bars else None)}


# ── the standard arm grid ──────────────────────────────────────────────────
def run_arm(rows: list[dict],
            signal_fn: Callable[[dict], dict | None],
            *, spread: float = SPREAD, min_rr: float = MIN_RR,
            extra_modes: tuple[tuple[str, dict], ...] = (),
            diagnose_zero: bool = True) -> dict:
    """Measure ONE arm three ways: plain / ladder / ladder_ts (+ extras).

    `ladder_ts` is the honest headline: the live exit ladder AND the live time
    exit. An arm whose natural hold is longer than the time exit loses its
    headline number under this row — that is the whole point.
    """
    ts = live_time_stop_bars(rows)
    out: dict[str, dict] = {}
    for label, kw in (("plain", {}), ("ladder", dict(LADDER)),
                      ("ladder_ts", dict(LADDER, time_stop_bars=ts)),
                      *extra_modes):
        res = backtest_ohlc(rows, signal_fn, min_rr=min_rr, spread=spread, **kw)
        out[label] = r_stats(res, time_stop_bars=ts)
    out["_time_stop_bars"] = ts
    if out["ladder"]["trades"] == 0 and diagnose_zero:
        out["zero_reason"] = diagnose(rows, signal_fn, min_rr=min_rr)["verdict"]
    return out


# ── dead-arm diagnosis (b69 class) ─────────────────────────────────────────
def capture_signals(rows: list[dict],
                    signal_fn: Callable[[dict], dict | None]) -> list[dict]:
    """Every non-None signal the arm emits, tagged with its bar index.

    DIAGNOSTIC ONLY — never feeds a measurement. It exists so `trades: 0` can
    be explained instead of being read as "no edge".
    """
    out: list[dict] = []
    for i, row in enumerate(rows):
        try:
            sig = signal_fn(row)
        except Exception as exc:          # a raising arm is itself a finding
            out.append({"_i": i, "_error": repr(exc)})
            continue
        if sig:
            out.append(dict(sig, _i=i))
    return out


def classify(sig: dict) -> str:
    """Which engine clause rejects this signal ('ok' if none does)."""
    side = str(sig.get("side", "")).upper()
    try:
        e, sl, tp = float(sig["entry"]), float(sig["sl"]), float(sig["tp"])
    except Exception:
        return "invalid_geometry"
    if side == "BUY" and not sl < e < tp:
        return "invalid_geometry"
    if side == "SELL" and not tp < e < sl:
        return "invalid_geometry"
    if side not in ("BUY", "SELL"):
        return "invalid_geometry"
    return "ok"


def diagnose(rows: list[dict],
             signal_fn: Callable[[dict], dict | None],
             *, min_rr: float = MIN_RR, min_grade: str | None = None) -> dict:
    """Name the clause that killed an arm (never let trades:0 be a conclusion)."""
    sigs = capture_signals(rows, signal_fn)
    errors = [s for s in sigs if "_error" in s]
    usable = [s for s in sigs if "_error" not in s]
    bad_geom = [s for s in usable if classify(s) != "ok"]
    good_geom = [s for s in usable if classify(s) == "ok"]
    low_rr = [s for s in good_geom if min_rr > 0 and
              abs(float(s["tp"]) - float(s["entry"])) /
              max(abs(float(s["entry"]) - float(s["sl"])), 1e-9) < min_rr]
    bad_grade = [s for s in good_geom if min_grade and
                 str(s.get("grade", "")).upper() > min_grade]
    counts = {"bars": len(rows), "signals": len(usable), "errors": len(errors),
              "invalid_geometry": len(bad_geom), "min_rr_rejected": len(low_rr),
              "grade_rejected": len(bad_grade)}
    counts["accepted"] = len(good_geom) - len(low_rr) - len(bad_grade)
    if not usable and errors:
        counts["verdict"] = f"raised: {errors[0]['_error']}"
    elif counts["signals"] == 0:
        counts["verdict"] = ("never_fired: the arm emitted 0 signals on this "
                             "dataset — the method was NEVER measured")
    elif counts["invalid_geometry"]:
        ex = bad_geom[0]
        counts["verdict"] = (f"invalid_geometry: {counts['invalid_geometry']}/"
                             f"{counts['signals']} signals have sl/entry/tp out "
                             f"of order (risk<=0), e.g. bar {ex.get('_i')} "
                             f"{ex.get('side')} entry={ex.get('entry')} "
                             f"sl={ex.get('sl')} — the b69 dead-arm shape")
    elif counts["min_rr_rejected"]:
        counts["verdict"] = f"min_rr: {counts['min_rr_rejected']} signals below gate"
    elif counts["grade_rejected"]:
        counts["verdict"] = f"grade: {counts['grade_rejected']} signals rejected"
    elif counts["accepted"]:
        counts["verdict"] = ("slot_occupied: signals passed every gate but the "
                             "one-position model never had a free slot")
    else:
        counts["verdict"] = "unknown"
    return counts


# ── honesty gate for a round's ledger ──────────────────────────────────────
class DishonestLedger(Exception):
    """Raised when a round's own results would mislead a reader."""


def check_honesty(name: str, row: dict, *, headline_delta: float = 0.15) -> list[str]:
    """Complaints (never raises) about one arm row in a round's ledger.

    * trades=0 without `zero_reason` → nothing was measured (b69 class);
    * no `ladder_ts` row → exp_R quoted without the live time exit (b71 class);
    * ladder mean hold > the time exit → a swing position on an intraday board;
    * exp_R moving more than `headline_delta` R under the time exit → the
      headline is exit-rule-sensitive, quote the ts number.
    """
    complaints: list[str] = []
    ladder = row.get("ladder") or {}
    ts = row.get("ladder_ts")
    if ladder.get("trades") == 0 and not row.get("zero_reason"):
        complaints.append(f"{name}: trades=0 with no zero_reason — nothing was "
                          "measured; run diagnose()")
    if ts is None:
        complaints.append(f"{name}: no ladder_ts row — exp_R quoted without the "
                          "live time exit (b71)")
        return complaints
    limit = row.get("_time_stop_bars") or 0
    mean_hold = ladder.get("mean_hold_bars")
    if limit and mean_hold and mean_hold > limit:
        complaints.append(f"{name}: mean hold {mean_hold} bars > live time exit "
                          f"{limit} bars — a swing position on an intraday board")
    p95_hold = ladder.get("p95_hold_bars")
    if limit and p95_hold and p95_hold > limit:
        complaints.append(f"{name}: p95 hold {p95_hold} bars > live time exit "
                          f"{limit} bars — the hold TAIL is swing-shaped even if "
                          "the mean is not (quote ladder_ts)")
    if ladder.get("exp_R") is not None and ts.get("exp_R") is not None:
        if abs(ladder["exp_R"] - ts["exp_R"]) > headline_delta:
            complaints.append(
                f"{name}: exp_R moves {ladder['exp_R']} -> {ts['exp_R']} under "
                "the live time exit — quote the ts number, not the ladder one")
    return complaints


def summarize(ledger: dict, arms: list[str]) -> list[str]:
    """Honesty complaints for every arm row in a round's ledger.

    A round whose summary is NOT empty must not quote the affected exp_R as a
    candidate number — print these lines next to the table.
    """
    out: list[str] = []
    for name in arms:
        row = ledger.get(name)
        if row is None:
            out.append(f"{name}: missing from the ledger")
            continue
        out.extend(check_honesty(name, row))
    return out


def print_table(ledger: dict, arms: list[str], *, label: str = "") -> None:
    """The standard round table: exp_R with the hold column beside it."""
    print(f"--- {label}" if label else "---")
    print(f"{'arm':26s} {'mode':10s} {'n':>5s} {'exp_R':>7s} {'net_R':>7s} "
          f"{'dd_R':>6s} {'meanH':>6s} {'p95H':>5s} {'maxH':>5s} {'>ts':>4s}")
    for name in arms:
        row = ledger.get(name) or {}
        for mode in ("plain", "ladder", "ladder_ts"):
            s = row.get(mode)
            if not s:
                continue
            print(f"{name:26s} {mode:10s} {s.get('trades') or 0:5d} "
                  f"{_fmt(s.get('exp_R')):>7s} {_fmt(s.get('net_R')):>7s} "
                  f"{_fmt(s.get('maxDD_R')):>6s} {_fmt(s.get('mean_hold_bars')):>6s} "
                  f"{_fmt(s.get('p95_hold_bars')):>5s} {_fmt(s.get('max_hold_bars')):>5s} "
                  f"{_fmt(s.get('holds_over_time_exit')):>4s}")
        if row.get("zero_reason"):
            print(f"{'':26s} ZERO REASON: {row['zero_reason']}")


def _fmt(v) -> str:
    return "-" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
