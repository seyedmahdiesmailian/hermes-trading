"""Real backtest engine — fetches OHLC from Bridge and runs strategy backtest."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from engines.context import build_plan_context
from engines.smc import smc_analyse, merge_smc_with_classic
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


def strategy_signal(row: dict, h1_window: list[dict], h4_window: list[dict], bar_index: int, m15_window: list[dict] | None = None, range_kill_conf: float = 0.35) -> dict | None:
    """Strategy function for backtest — runs the EXACT live funnel.

    No hand-copied gates: builds the plan with build_plan_from_context and
    routes the bar through evaluate_monitor_cycle, the same two functions
    hermes_runtime.cycle uses. Live only ever executes on
    action == 'market_entry_now' (_build_proposal ignores pending actions),
    so that is the only signal the backtest may emit. Parity by construction.
    """
    m15_window = m15_window or []
    if bar_index < 30 or len(h1_window) < 10 or len(m15_window) < 30:
        return None

    try:
        now = datetime.fromtimestamp(row.get("time", 0), tz=timezone.utc)
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
        classic_regime = ctx.get("quality", {}).get("regime", "")
        smc_confidence = float(merged.get("confidence", 0) or 0)
        smc_bias = merged.get("bias", "neutral")
        # same range-kill rule as build_live_plan (threshold overridable for A/B)
        if classic_regime == "range" and smc_bias != "neutral" and smc_confidence < range_kill_conf:
            ctx["bias"] = "neutral"
            merged["bias"] = "neutral"
            merged["confidence"] = min(smc_confidence, 0.3)
        else:
            ctx["bias"] = merged.get("bias", ctx.get("bias"))
        ctx.setdefault("quality", {})["smc_confidence"] = merged.get("confidence")

        plan = build_plan_from_context(ctx, now=now)
        decision = evaluate_monitor_cycle(plan, price=float(row.get("close", 0)), now=now)
        if decision.get("action") != "market_entry_now":
            return None
        bp = decision.get("blueprint") or {}
        if not bp:
            return None
        # grade parity: live auto_executor Check 6 kills C-grade entries
        # (MIN_SETUP_GRADE="B"). Without this the backtest silently traded
        # every stale-plan C setup the live funnel would reject.
        from hermes_runtime import _infer_setup_grade
        return {"side": bp["side"], "entry": float(bp["entry_price"]),
                "sl": float(bp["sl"]), "tp": float(bp["tp"]),
                "style": decision.get("execution_style"),
                "grade": _infer_setup_grade(plan)}
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
                 partial_share_fn=None) -> dict:
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

    def signal_fn(row):
        idx = row_index.get(id(row), 0)
        # Slice H1 and H4 windows up to this bar's approximate time —
        # window sizes must match live (80/80), not 30/15.
        bar_time = row.get("time", 0)
        h1_window = [r for r in h1_data if r.get("time", 0) <= bar_time][-80:]
        h4_window = [r for r in h4_data if r.get("time", 0) <= bar_time][-80:]
        m15_window = m15_data[max(0, idx - 120):idx + 1]
        return strategy_signal(row, h1_window, h4_window, idx, m15_window=m15_window,
                               range_kill_conf=range_kill_conf)

    result = backtest_ohlc(
        m15_data,
        signal_fn,
        min_rr=min_rr,         # live gate 6: backtested MIN_RR (A/B-able)
        min_grade=min_grade,  # live gate 7: MIN_SETUP_GRADE="B" (parity; None = measure-only)
        breakeven_at_r=breakeven_at_r,   # live trade management: BE move at +0.5R (A/B-able)
        partial_tp1_share=partial_tp1_share,  # live TP ladder: 50% at first target (A/B-able)
        tp1_position=tp1_position,
        partial_share_fn=partial_share_fn,    # b54c: grade-aware ladder (mirrors _partial_close_fraction)
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
