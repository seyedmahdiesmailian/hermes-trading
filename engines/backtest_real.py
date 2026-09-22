"""Real backtest engine — fetches OHLC from Bridge and runs strategy backtest."""
from __future__ import annotations

import bisect
import json
from datetime import datetime, timezone
from pathlib import Path
from engines.context import build_plan_context, apply_bias_geometry
from engines.smc import smc_analyse, merge_smc_with_classic
from engines.trade_management import ladder_fields
from engines.plan import apply_smc_merge
from engines.orchestrator import build_plan_from_context, evaluate_monitor_cycle
from engines.backtest import backtest_ohlc
from engines import paths as _paths

RESULTS_DIR = None  # b39: removed — see _results_dir(); a module-level Path
                    # here also mkdir'd production data/ at IMPORT time.


def _results_dir() -> Path:
    """Backtest artifacts land under the ACTIVE data root, resolved per call
    (b39): the old `RESULTS_DIR = Path('/home/ai/hermes-trading/data/backtest')`
    plus a module-level mkdir meant that merely IMPORTING this module created a
    directory in production state, even from a test run."""
    d = _paths.data_dir() / 'backtest'
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_all_ohlc(bridge, symbol: str = "XAUUSD", timeframe: str = "H1", count: int = 500) -> list[dict]:
    """Fetch OHLC data from Bridge. Handles pagination if needed."""
    all_rows = []
    resp = bridge.get_rates(symbol, timeframe, count)
    if isinstance(resp, dict) and resp.get("ok"):
        data = resp.get("data", resp.get("rates", []))
        if isinstance(data, list):
            all_rows = data
    return all_rows


def settled_m5_rows(m5_stream: list[dict] | None, now_epoch: int,
                    limit: int = 12) -> list[dict]:
    """b189 — the M5 window hermes_runtime.cycle hands to the monitor.

    Live fetches the last 12 M5 rows and KEEPS only settled ones:
    `bar_time + 300 <= now` (the bridge returns the FORMING bar last, and
    counting its close would be lookahead). This is that filter, verbatim, so
    the lab's trigger window is the same set of bars live could have seen at
    this decision moment — no more, no less.

    `now_epoch` is the decision moment. For a backtest bar that opened at
    `bar_time` and spans `span` seconds, the decision runs on the bar's CLOSE,
    i.e. at `bar_time + span` — which is why an M5 entry stream's current bar
    counts as settled here (it closed at exactly that instant).
    """
    if not m5_stream:
        return []
    out = [r for r in m5_stream
           if isinstance(r.get("time"), (int, float))
           and r["time"] + M5_BAR_SECONDS <= now_epoch]
    return out[-limit:]


M5_BAR_SECONDS = 300  # live TIMEFRAME='M5'; hermes_runtime uses `+ 300 <= now`


def m5_window_for(m5_stream: list[dict], m5_times: list[int],
                  decision_epoch) -> list[dict]:
    """b189 — the settled-M5 window live would hold at `decision_epoch`.

    ONE implementation of the slice, shared by `run_backtest`'s signal_fn and
    by `scripts.b190_merit_bar_live_trigger.coverage` (the trigger-fires-there
    census), so the paths cannot price the b187 trigger off different bar sets
    (the b109/b169 class). NOTE (b190, measured): `scripts.b81_lane_rescore.
    funnel_fn` does NOT call this — it invokes `strategy_signal` without
    `m5_rows` on M15 windows, which derives nothing — so every b81-based
    ledger (b117/b118/b109/b119...) prices the funnel trigger-LESS; that is
    exactly the gap the b190 re-baseline was built to price.
    """
    if not m5_stream or not isinstance(decision_epoch, (int, float)):
        return []
    cut = bisect.bisect_right(m5_times, int(decision_epoch))
    return settled_m5_rows(m5_stream[max(0, cut - 12):cut], int(decision_epoch))



def strategy_signal(row: dict, h1_window: list[dict], h4_window: list[dict], bar_index: int, m15_window: list[dict] | None = None, range_kill_conf: float = 0.35, m5_rows: list[dict] | None = None, derive_m5: bool = True) -> dict | None:
    """Strategy function for backtest — runs the EXACT live funnel.

    No hand-copied gates: builds the plan with build_plan_from_context and
    routes the bar through evaluate_monitor_cycle, the same two functions
    hermes_runtime.cycle uses. Live only ever executes on
    action == 'market_entry_now' (_build_proposal ignores pending actions),
    so that is the only signal the backtest may emit. Parity by construction.

    b187 PARITY (this is the fix for todo b189): live's monitor call gets
    `m5_rows=` the settled M5 closes, because b187 replaced the zone-touch
    trigger with an M5 3-close confirmation. Until now the backtest called
    evaluate_monitor_cycle WITHOUT them, so `m5_confirmation` could never pass
    and every in-zone (pullback) signal the funnel still emitted was priced on
    a rule live never runs. `m5_rows` is threaded through here exactly as
    hermes_runtime threads it into the same function; when it is not supplied,
    it is DERIVED from the entry window whenever that window is itself an M5
    stream (live-parity), and left empty otherwise — so an M15 leg without an
    M5 source reproduces the pre-b189 numbers byte-identically.
    """
    m15_window = m15_window or []
    if bar_index < 30 or len(h1_window) < 10 or len(m15_window) < 30:
        return None

    try:
        now = datetime.fromtimestamp(row.get("time", 0), tz=timezone.utc)
        # b189: the live-parity entry stream IS M5 (hermes_runtime TIMEFRAME),
        # so when no explicit window was supplied, derive the settled-M5 rows
        # from the tail of the entry window exactly as hermes_runtime builds
        # them: the decision runs on the current bar's close (its open + 300),
        # so the current row is settled and older rows are too; a forming row
        # cannot appear in a closed-bar backtest window at all. Any other
        # spacing (M15 legs) derives NOTHING — the trigger stays unfired and
        # every stored pre-b189 M15 number is byte-identical.
        if m5_rows is None and derive_m5:
            _rt = row.get("time")
            if isinstance(_rt, (int, float)) and len(m15_window) >= 2:
                _tail = m15_window[-20:]
                _g = sorted(int(_tail[i + 1]["time"]) - int(_tail[i]["time"])
                            for i in range(len(_tail) - 1)
                            if isinstance(_tail[i].get("time"), (int, float))
                            and isinstance(_tail[i + 1].get("time"), (int, float)))
                _g = [x for x in _g if x > 0]
                if _g and _g[len(_g) // 2] == M5_BAR_SECONDS:
                    m5_rows = settled_m5_rows(m15_window,
                                              int(_rt) + M5_BAR_SECONDS) or None

        # session detection identical to live _detect_session:
        # 0-7 asia, 7-13 london, 13-24 newyork
        h = now.hour
        if 0 <= h < 7:
            session = "asia"
        elif 7 <= h < 13:
            session = "london"
        else:
            session = "newyork"
        # NOTE: m15_window here is the ENTRY stream (M5 in live-parity runs),
        # not real M15 bars — so no analytical m15 vote is recorded in backtest.
        # The vote is a live-reporting field only and never decides entries.
        ctx = build_plan_context(m15_window[-120:], h1_window[-80:], h4_window[-80:], session)
        smc_result = smc_analyse(m15_window[-120:], now=now, h1_rows=h1_window[-80:])
        merged = merge_smc_with_classic(ctx, smc_result)
        # b193: this was a hand-copy of build_live_plan's merge block that never
        # carried b188(a)'s stale-at-birth veto — live kills those plans at the
        # merge, the lab kept trading them (11 of 523 signals on the cached M15
        # leg). Both paths now call the ONE definition in engines.plan;
        # smc_result is deliberately not passed (display-only stamps, never read
        # by the funnel). The veto itself is stamped by apply_smc_merge into
        # ctx['quality']['stale_at_birth'], which build_plan_from_context copies
        # onto the plan exactly as the live path does.
        apply_smc_merge(ctx, merged, entry_close=float(row.get("close", 0) or 0),
                        range_kill_conf=range_kill_conf,
                        rebuild=apply_bias_geometry)

        plan = build_plan_from_context(ctx, now=now)
        decision = evaluate_monitor_cycle(plan, price=float(row.get("close", 0)),
                                          now=now, m5_rows=m5_rows)
        if decision.get("action") != "market_entry_now":
            return None
        bp = decision.get("blueprint") or {}
        if not bp:
            return None
        # grade parity: live auto_executor Check 6 kills C-grade entries
        # (MIN_SETUP_GRADE="B"). Without this the backtest silently traded
        # every stale-plan C setup the live funnel would reject.
        from hermes_runtime import _infer_setup_grade
        grade = _infer_setup_grade(plan)
        # b109: the trade dict the ladder reads must be built from LIVE
        # semantics, not a lookalike. Until now the backtest handed the real
        # _partial_close_fraction a dict with none of the four fields it reads
        # (setup_grade/momentum_strength/rr_remaining/structure_state), so
        # rr_remaining defaulted to 0.0, the `<= 1.2` branch tripped on every
        # call and the "live-parity ladder" was the constant (1.0,
        # weak_full_exit_at_tp1) — 935/935 calls on the cached funnel, the
        # 84 A-grade signals included. Emit them through the SAME helper the
        # live producers use (engines.trade_management.ladder_fields), so the
        # parity claim is by construction again.
        sig = {"side": bp["side"], "entry": float(bp["entry_price"]),
               "sl": float(bp["sl"]), "tp": float(bp["tp"]),
               "style": decision.get("execution_style"),
               "grade": grade}
        sig.update(ladder_fields(plan.get("quality") or {}, grade,
                                 session=plan.get("session")))
        return sig
    except Exception:
        return None


def run_backtest(bridge, symbol: str = "XAUUSD", timeframe: str = "M15", count: int = 500,
                 exclude_styles: list[str] | None = None, data: dict | None = None,
                 range_kill_conf: float = 0.35,
                 spread_override: float | None = None,
                 # b53 PARITY FIX: live has NO standalone breakeven-at-+XR move.
                 # trade_management.py only brings SL to entry AFTER a TP fill
                 # (the partial branch), which backtest_ohlc already models via
                 # partial_tp1_share. The old 0.5 default simulated a rule live
                 # never runs — it inflated scratches 32x and hid the true
                 # live result (be=0: 149 trades / 73.8% WR / +1040 vs the
                 # phantom +943). 0.0 = honest live geometry.
                 breakeven_at_r: float = 0.0,
                 min_grade: str | None = "B",
                 min_rr: float = 1.5,
                 partial_tp1_share: float = 0.5,
                 tp1_position: float = 0.5,
                 partial_share_fn=None,
                 trail_after_partial: float = 0.0,   # b55c: live-parity trail after TP1
                 trail_floor: float = 0.0,           # b117: live's absolute $ floor
                                                     # under the trail distance
                                                     # (max(risk*mult, 3.0)); 0 = off
                 time_stop_bars: int = 0,
                 # b189: an explicit M5 stream to price the b187 trigger against
                 # (needed when the ENTRY stream is coarser than M5, e.g. the
                 # M15 legs cached in data/backtest). None = derive from the
                 # entry stream when it is itself M5, else no trigger rows.)
                 m5_stream: list[dict] | None = None) -> dict:   # b57: dead-trade time stop
    """Run backtest on real OHLC data from Bridge.

    exclude_styles: drop signals whose decision execution_style matches one of
    these prefixes (e.g. ["aggressive"] disables every aggressive entry path).
    data: optional pre-fetched {"M15": [...], "H1": [...], "H4": [...]} so
    A/B comparisons run on byte-identical datasets instead of re-fetching.
    spread_override: replace the live-parity 0.20 round-trip cost (cost-model
    sensitivity analysis only — never used by the live path).
    """
    # Fetch data — entry timeframe must match live TIMEFRAME (M5); the
    # internal variable keeps the m15_ name for the cached-data key compat.
    if data:
        m15_data = data.get(timeframe) or data.get("M15") or []
        h1_data = data.get("H1") or []
        h4_data = data.get("H4") or []
    else:
        m15_data = fetch_all_ohlc(bridge, symbol, timeframe, count)
        h1_data = fetch_all_ohlc(bridge, symbol, "H1", count)
        h4_data = fetch_all_ohlc(bridge, symbol, "H4", count)

    if not m15_data or not h1_data or not h4_data:
        return {"ok": False, "error": "insufficient_data", "counts": {"M15": len(m15_data), "H1": len(h1_data), "H4": len(h4_data)}}

    # index map: live passes full 120/80/80 windows; list.index(row) on dicts
    # was O(n) per bar (6500 bars → O(n^2) scan). Precompute once.
    row_index = {id(r): i for i, r in enumerate(m15_data)}

    # b189: the decision moment on a backtest bar is its CLOSE, so the live
    # `now` for the settled-M5 filter is bar_time + bar spacing. Median spacing
    # of the entry stream (lab_harness.bar_seconds' robust convention) is the
    # only honest reading of a dataset that carries no explicit timeframe tag.
    _gaps = sorted(int(m15_data[i + 1]["time"]) - int(m15_data[i]["time"])
                   for i in range(len(m15_data) - 1)
                   if isinstance(m15_data[i].get("time"), (int, float))
                   and isinstance(m15_data[i + 1].get("time"), (int, float)))
    _gaps = [g for g in _gaps if g > 0]
    bar_spacing = _gaps[len(_gaps) // 2] if _gaps else M5_BAR_SECONDS
    # b189: which stream prices the trigger? None = auto (an M5 entry stream IS
    # live's TIMEFRAME, so its own closed rows do); an explicit [] = "price the
    # funnel with NO confirmation rows" (the pre-b187 arm, an A/B control);
    # a real list = price against that M5 source (e.g. an M15 leg measured
    # against the broker's M5 closes). m5_times must be ascending, which every
    # bridge/cached dataset is.
    if m5_stream is None:
        m5_stream = m15_data if bar_spacing == M5_BAR_SECONDS else []
    m5_stream = m5_stream or []
    m5_times = [int(r.get("time", 0)) for r in m5_stream]

    def signal_fn(row):
        idx = row_index.get(id(row), 0)
        # Slice H1 and H4 windows up to this bar's approximate time —
        # window sizes must match live (80/80), not 30/15.
        bar_time = row.get("time", 0)
        h1_window = [r for r in h1_data if r.get("time", 0) <= bar_time][-80:]
        h4_window = [r for r in h4_data if r.get("time", 0) <= bar_time][-80:]
        m15_window = m15_data[max(0, idx - 120):idx + 1]
        # b189: the live decision moment is the bar's CLOSE, so a row counts as
        # settled when its own close happened at or before that instant. With
        # no M5 source at all (an M15 leg with m5_stream=None) the window is
        # empty, the b187 trigger can never fire, and the run reproduces the
        # pre-b189 numbers byte-identically.
        _m5 = m5_window_for(m5_stream, m5_times,
                            (bar_time or 0) + bar_spacing)
        return strategy_signal(row, h1_window, h4_window, idx, m15_window=m15_window,
                               range_kill_conf=range_kill_conf, m5_rows=_m5)

    result = backtest_ohlc(
        m15_data,
        signal_fn,
        min_rr=min_rr,         # live gate 6: backtested MIN_RR (A/B-able)
        min_grade=min_grade,  # live gate 7: MIN_SETUP_GRADE="B" (parity; None = measure-only)
        breakeven_at_r=breakeven_at_r,   # live trade management: BE move at +0.5R (A/B-able)
        partial_tp1_share=partial_tp1_share,  # live TP ladder: 50% at first target (A/B-able)
        tp1_position=tp1_position,
        partial_share_fn=partial_share_fn,    # b54c: grade-aware ladder (mirrors _partial_close_fraction)
        trail_after_partial=trail_after_partial,  # b55c: mirror live trailing stop after TP1
        trail_floor=trail_floor,              # b117: mirror live's max(risk*mult, $floor)
        time_stop_bars=time_stop_bars,            # b57: dead-trade time stop
        spread=spread_override if spread_override is not None else 0.20,  # XAUUSD demo round-trip cost
        exclude_styles=exclude_styles,
    )
    result["ok"] = True
    result["symbol"] = symbol
    result["timeframe"] = timeframe
    result["bars_tested"] = len(m15_data)
    result["data_range"] = {
        "from": m15_data[0].get("time") if m15_data else None,
        "to": m15_data[-1].get("time") if m15_data else None,
    }

    return result


def save_backtest_result(result: dict, label: str = ""):
    """Save backtest result to disk."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"backtest_{label}_{ts}.json" if label else f"backtest_{ts}.json"
    path = _results_dir() / fname
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(path)
