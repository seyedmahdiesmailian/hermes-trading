"""Pre-session macro & multi-TF context — migrated from legacy mt5_xau_presession.py.

Legacy source: Hermes_Full_Backup trading/xau_plan/current_presession.json +
skills/trading/mt5-direct-api-control/references/pending-orders-and-presession-fixes.md

Builds a compact macro snapshot before/at plan time:
  - DXY direction & strength (from 6 USD pairs via bridge rates)
  - Silver (XAGUSD) confirmation for gold direction
  - Risk sentiment proxy (US500/SPX if broker exposes it, else unavailable)
  - Tick-volume ratio (current activity vs 20-bar average)
  - H4/D1/W1 zone position (premium/discount/equilibrium + 20-bar levels)

Output feeds plan building as context["macro"] and is rendered in reports.
Broker symbols that don't exist are skipped gracefully (available: false).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

DXY_COMPONENTS = ["EURUSD", "USDJPY", "GBPUSD", "USDCAD", "USDCHF", "AUDUSD"]
HTF_TIMEFRAMES = ["H4", "D1", "W1"]


def _pct(a: float, b: float) -> float:
    if not b:
        return 0.0
    return round((a - b) / b * 100.0, 3)


def _zone(pos: float) -> str:
    if pos >= 0.8:
        return "premium"
    if pos <= 0.2:
        return "discount"
    return "equilibrium"


def _direction(v: float, thresh: float = 0.05) -> str:
    if v > thresh:
        return "up"
    if v < -thresh:
        return "down"
    return "flat"


def analyze_macro(bridge, symbol: str = "XAUUSD") -> dict:
    """Collect macro snapshot. Never raises — missing data = available:false."""
    out: dict = {"timestamp": datetime.now(timezone.utc).isoformat()}

    # ── DXY proxy from 6 majors ──
    comps = {}
    for s in DXY_COMPONENTS:
        try:
            t = bridge.get_tick(s)
            data = t.get("data", t) if isinstance(t, dict) else {}
            bid, ask = float(data.get("bid", 0) or 0), float(data.get("ask", 0) or 0)
            if bid > 0:
                comps[s] = (bid + ask) / 2.0
        except Exception:
            continue
    # real DXY if broker has it, else synthetic estimate from components
    dxy_change = None
    try:
        t = bridge.get_tick("USDX")  # some brokers: USDX / DXY / USDIndex
        data = t.get("data", t) if isinstance(t, dict) else {}
        if float(data.get("bid", 0) or 0) > 0:
            out["dxy"] = {"value": float(data.get("bid")), "available": True, "source": "broker"}
    except Exception:
        pass
    if "dxy" not in out and len(comps) >= 4:
        # synthetic direction: EUR+GBP+AUD down = dollar up, etc.
        usd_moves = []
        for s, px in comps.items():
            try:
                r = bridge.get_rates(s, "H1", 2)
                rows = r.get("data", []) if isinstance(r, dict) else []
                if len(rows) >= 2:
                    prev = float(rows[-2].get("close", 0) or 0)
                    if prev:
                        base = _pct(px, prev)
                        usd_moves.append(-base if s in ("EURUSD", "GBPUSD", "AUDUSD") else base)
            except Exception:
                continue
        if usd_moves:
            avg = sum(usd_moves) / len(usd_moves)
            dxy_change = round(avg, 3)
            out["dxy"] = {
                "change_pct": dxy_change,
                "direction": _direction(dxy_change, 0.02),
                "available": True,
                "source": "synthetic",
            }
    if "dxy" not in out:
        out["dxy"] = {"available": False}

    # ── Silver confirmation ──
    for sym in ("XAGUSD", "SILVER", "XAG"):
        try:
            t = bridge.get_tick(sym)
            data = t.get("data", t) if isinstance(t, dict) else {}
            bid = float(data.get("bid", 0) or 0)
            if bid > 0:
                r = bridge.get_rates(sym, "H1", 2)
                rows = r.get("data", []) if isinstance(r, dict) else []
                chg = 0.0
                if len(rows) >= 2:
                    prev = float(rows[-2].get("close", 0) or 0)
                    chg = _pct(bid, prev)
                out["silver"] = {
                    "value": bid,
                    "change_pct": chg,
                    "direction": _direction(chg),
                    "bullish_for_gold": chg > 0.05,
                    "available": True,
                }
                break
        except Exception:
            continue
    if "silver" not in out:
        out["silver"] = {"available": False}

    # ── Risk sentiment (US500 / SPX / US30 fallback) ──
    for sym in ("US500", "SPX", "US30", "NAS100"):
        try:
            t = bridge.get_tick(sym)
            data = t.get("data", t) if isinstance(t, dict) else {}
            bid = float(data.get("bid", 0) or 0)
            if bid > 0:
                r = bridge.get_rates(sym, "H1", 2)
                rows = r.get("data", []) if isinstance(r, dict) else []
                chg = 0.0
                if len(rows) >= 2:
                    prev = float(rows[-2].get("close", 0) or 0)
                    chg = _pct(bid, prev)
                out["risk_sentiment"] = {
                    "symbol": sym,
                    "change_pct": chg,
                    "risk_mode": "risk_on" if chg > 0.05 else ("risk_off" if chg < -0.05 else "neutral"),
                    "available": True,
                }
                break
        except Exception:
            continue
    if "risk_sentiment" not in out:
        out["risk_sentiment"] = {"available": False}

    # ── Tick volume ratio ──
    try:
        r = bridge.get_rates(symbol, "M15", 21)
        rows = r.get("data", []) if isinstance(r, dict) else []
        vols = [float(x.get("volume", x.get("tick_volume", 0)) or 0) for x in rows]
        vols = [v for v in vols if v > 0]
        if len(vols) >= 6:
            cur, avg = vols[-1], sum(vols[:-1]) / (len(vols) - 1)
            ratio = round(cur / avg, 2) if avg else 0.0
            out["tick_volume"] = {
                "volume_ratio": ratio,
                "is_high_volume": ratio >= 1.3,
                "is_low_volume": ratio <= 0.6,
                "available": True,
            }
    except Exception:
        pass
    if "tick_volume" not in out:
        out["tick_volume"] = {"available": False}

    # ── HTF zone positions (H4/D1/W1) ──
    htf = {}
    for tf in HTF_TIMEFRAMES:
        try:
            r = bridge.get_rates(symbol, tf, 25)
            rows = r.get("data", []) if isinstance(r, dict) else []
            if len(rows) >= 21:
                highs = [float(x["high"]) for x in rows]
                lows = [float(x["low"]) for x in rows]
                closes = [float(x["close"]) for x in rows]
                hi20, lo20 = max(highs[-20:]), min(lows[-20:])
                price = closes[-1]
                rng = hi20 - lo20
                pos = round((price - lo20) / rng, 2) if rng > 0 else 0.5
                sma10 = round(sum(closes[-10:]) / 10.0, 2)
                htf[tf.lower()] = {
                    "price": price,
                    "high_20": hi20,
                    "low_20": lo20,
                    "pos_in_range": pos,
                    "zone": _zone(pos),
                    "sma10": sma10,
                    "trend": "bullish" if price > sma10 else "bearish",
                }
        except Exception:
            continue
    out["higher_tf"] = htf

    return out


def gold_macro_verdict(macro: dict) -> dict:
    """Interpret macro snapshot for XAUUSD: supports_long/short/none."""
    score_long = 0
    score_short = 0
    dxy = macro.get("dxy") or {}
    if dxy.get("available"):
        if dxy.get("direction") == "down":
            score_long += 1      # weaker dollar → gold up
        elif dxy.get("direction") == "up":
            score_short += 1
    silver = macro.get("silver") or {}
    if silver.get("available"):
        if silver.get("bullish_for_gold"):
            score_long += 1
        elif silver.get("direction") == "down":
            score_short += 1
    risk = macro.get("risk_sentiment") or {}
    if risk.get("available"):
        if risk.get("risk_mode") == "risk_off":
            score_long += 1      # safe haven
        elif risk.get("risk_mode") == "risk_on":
            score_short += 1
    verdict = "none"
    if score_long >= 2 and score_long > score_short:
        verdict = "supports_long"
    elif score_short >= 2 and score_short > score_long:
        verdict = "supports_short"
    return {
        "verdict": verdict,
        "score_long": score_long,
        "score_short": score_short,
        "macro_conflicting": score_long > 0 and score_short > 0,
    }
