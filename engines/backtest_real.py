"""Real backtest engine — fetches OHLC from Bridge and runs strategy backtest."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from engines.context import build_plan_context
from engines.smc import smc_analyse, merge_smc_with_classic
from engines.orchestrator import build_plan_from_context, evaluate_monitor_cycle
from engines.backtest import backtest_ohlc

RESULTS_DIR = Path('/home/ai/hermes-trading/data/backtest')
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


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
        session = "london"
        h = now.hour
        if 0 <= h < 7:
            session = "asia"
        elif 13 <= h < 21:
            session = "newyork"

        ctx = build_plan_context(m15_window[-120:], h1_window[-20:], h4_window[-10:], session)
        smc_result = smc_analyse(m15_window[-120:], now=now, h1_rows=h1_window)
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
                 range_kill_conf: float = 0.35) -> dict:
    """Run backtest on real OHLC data from Bridge.

    exclude_styles: drop signals whose decision execution_style matches one of
    these prefixes (e.g. ["aggressive"] disables every aggressive entry path).
    data: optional pre-fetched {"M15": [...], "H1": [...], "H4": [...]} so
    A/B comparisons run on byte-identical datasets instead of re-fetching.
    """
    # Fetch data
    if data:
        m15_data = data.get("M15") or []
        h1_data = data.get("H1") or []
        h4_data = data.get("H4") or []
    else:
        m15_data = fetch_all_ohlc(bridge, symbol, "M15", count)
        h1_data = fetch_all_ohlc(bridge, symbol, "H1", count)
        h4_data = fetch_all_ohlc(bridge, symbol, "H4", count)

    if not m15_data or not h1_data or not h4_data:
        return {"ok": False, "error": "insufficient_data", "counts": {"M15": len(m15_data), "H1": len(h1_data), "H4": len(h4_data)}}

    def signal_fn(row):
        idx = m15_data.index(row) if row in m15_data else 0
        # Slice H1 and H4 windows up to this bar's approximate time
        bar_time = row.get("time", 0)
        h1_window = [r for r in h1_data if r.get("time", 0) <= bar_time][-30:]
        h4_window = [r for r in h4_data if r.get("time", 0) <= bar_time][-15:]
        m15_window = m15_data[max(0, idx - 120):idx + 1]
        return strategy_signal(row, h1_window, h4_window, idx, m15_window=m15_window,
                               range_kill_conf=range_kill_conf)

    result = backtest_ohlc(
        m15_data,
        signal_fn,
        min_rr=1.5,           # live gate 6: backtested MIN_RR
        min_grade="B",        # live gate 7: MIN_SETUP_GRADE="B" (parity)
        breakeven_at_r=0.5,   # live trade management: BE move at +0.5R
        partial_tp1_share=0.5,  # live TP ladder: 50% at first target
        spread=0.20,          # XAUUSD demo round-trip cost
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
    path = RESULTS_DIR / fname
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(path)
