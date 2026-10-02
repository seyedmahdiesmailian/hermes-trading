"""
XAUUSD Decision Collector — collects ALL market data and analysis for Hermes decision-loop.

Output to stdout:
  - JSON block with full machine-readable context
  - Human-readable Persian summary for Hermes (LLM) to reason about

Architecture:
  This script = "eyes" — sees everything, analyzes nothing beyond what code already does.
  Hermes (LLM) = "brain" — reads this output, decides, executes.
  Runtime executor = "hands" — only executes decisions.

Flow:
  1. Connect MT5 - get data (M15, H1, H4, tick, account)
  2. Run macro context (DXY proxy, SPX risk, silver, volume, H4/D1/W1)
  3. Run classic analysis (bias, value zone, regime, ATR)
  3. Run SMC analysis (17 concepts, M15 + H1)
  4. Merge classic + SMC
  5. Check heartbeat (Hermes active? fallback?)
  6. Check open positions + pending orders
  7. Check risk limits + account policy
  8. Output full structured context
"""

import json
import sys
from datetime import datetime, timezone

# ── Path setup ──
SCRIPTS_DIR = r"C:\Users\Administrator\AppData\Local\hermes\scripts"
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


def _now() -> datetime:
    return datetime.now()


# ═══════════════════════════════════════════════════════════════════════════════
# Data collection
# ═══════════════════════════════════════════════════════════════════════════════

def _collect_raw_data():
    """Collect all raw MT5 data. Returns dict with all timeframes + account."""
    import MetaTrader5 as mt5

    result = {"mt5_connected": False, "error": None}

    if not mt5.initialize():
        result["error"] = f"mt5.initialize failed: {mt5.last_error()}"
        return result

    result["mt5_connected"] = True

    def _rows(symbol, timeframe, count):
        data = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if data is None:
            return []
        return [
            {"time": int(r["time"]), "open": float(r["open"]),
             "high": float(r["high"]), "low": float(r["low"]),
             "close": float(r["close"])}
            for r in data
        ]

    result["m5"]  = _rows("XAUUSD", mt5.TIMEFRAME_M5,  100)
    result["m15"] = _rows("XAUUSD", mt5.TIMEFRAME_M15, 80)
    result["h1"]  = _rows("XAUUSD", mt5.TIMEFRAME_H1,  80)
    result["h4"]  = _rows("XAUUSD", mt5.TIMEFRAME_H4,  80)

    # Current tick
    tick = mt5.symbol_info_tick("XAUUSD")
    if tick:
        spread = round((float(tick.ask) - float(tick.bid)) * 100, 1) if tick.ask and tick.bid else 0
        result["tick"] = {"bid": float(tick.bid), "ask": float(tick.ask),
                          "time": int(tick.time), "spread": spread}
    else:
        result["tick"] = None

    # Account
    acc = mt5.account_info()
    if acc:
        result["account"] = {
            "login": int(acc.login),
            "balance": float(acc.balance),
            "equity": float(acc.equity),
            "margin": float(acc.margin),
            "margin_free": float(acc.margin_free),
            "profit": float(acc.profit),
            "currency": acc.currency,
        }

    # Open positions
    positions = mt5.positions_get(symbol="XAUUSD")
    result["open_positions"] = []
    if positions:
        for p in positions:
            result["open_positions"].append({
                "ticket": int(p.ticket),
                "type": "BUY" if p.type == 0 else "SELL",
                "volume": float(p.volume),
                "open_price": float(p.price_open),
                "current_price": float(p.price_current),
                "sl": float(p.sl),
                "tp": float(p.tp),
                "profit": float(p.profit),
                "comment": p.comment,
                "open_time": int(p.time),
            })

    mt5.shutdown()
    return result


def _collect_macro_snapshot() -> dict:
    """Collect macro snapshot (DXY proxy, SPX, silver, volume, higher TFs).
    Returns dict with 'market_open' and full macro data."""
    try:
        import MetaTrader5 as mt5
        from mt5_xau_macro import build_macro_snapshot
        if not mt5.initialize():
            return {"market_open": False}
        snap = build_macro_snapshot(mt5)
        # Market open check: last quote time must be recent (< 5 min)
        sym_info = mt5.symbol_info("XAUUSD")
        if sym_info and sym_info.time:
            from datetime import datetime as dt
            quote_age_sec = (dt.now().timestamp() - sym_info.time)
            snap["market_open"] = quote_age_sec < 300  # 5 min threshold
            snap["quote_age_sec"] = round(quote_age_sec)
        else:
            snap["market_open"] = False
        mt5.shutdown()
        return snap
    except Exception:
        return {"market_open": False}


# ═══════════════════════════════════════════════════════════════════════════════
# Analysis
# ═══════════════════════════════════════════════════════════════════════════════

def _run_analysis(raw: dict, now: datetime) -> dict:
    """Run classic + SMC + macro analysis on raw data."""
    from mt5_xau_context import build_plan_context
    from mt5_xau_smc import smc_analyse, merge_smc_with_classic
    from mt5_account_risk import assess_account_policy, recommend_risk_budget
    from mt5_xau_heartbeat import check_hermes_status
    from mt5_xau_storage import load_performance_state
    from mt5_xau_macro import build_macro_snapshot

    m5  = raw.get("m5",  [])
    m15 = raw.get("m15", [])
    h1  = raw.get("h1",  [])
    h4  = raw.get("h4",  [])

    if not (m5 and m15 and h1 and h4):
        return {"error": "insufficient_data", "analysis_ok": False}

    # Session detection
    from mt5_xau_session import get_session, get_active_killzones, session_risk_adjustment, is_high_quality_window
    now_dt = now or _now()
    sess = get_session(now_dt)
    kzs = get_active_killzones(now_dt)
    session = sess["name"]
    # Use local hour for backward compat
    hour = now_dt.hour

    # Classic analysis (M15 + H1 + H4)
    try:
        classic = build_plan_context(m15, h1, h4, session)
    except Exception as e:
        return {"error": f"classic_analysis_failed: {e}", "analysis_ok": False}

    # M5 Classic (fast entry timing)
    m5_classic = {}
    try:
        m5_classic = build_plan_context(m5, m5, m15, session)
        m5_classic["bias"] = m5_classic.get("bias", "neutral")
        m5_classic["atr"] = m5_classic.get("atr", 0)
    except Exception:
        m5_classic = {"bias": "neutral", "atr": 0}

    # SMC analysis (M15 + H1)
    try:
        smc = smc_analyse(m15, now=now, h1_rows=h1)
        merged = merge_smc_with_classic(classic, smc)
    except Exception as e:
        return {"error": f"smc_analysis_failed: {e}", "analysis_ok": False}

    # M5 SMC (entry-level precision)
    m5_smc = {}
    try:
        m5_smc = smc_analyse(m5, now=now, h1_rows=m15)
        m5_smc["bias"] = m5_smc.get("bias", "neutral")
        m5_smc["confidence"] = m5_smc.get("confidence", 0.0)
        m5_smc["fvgs"] = m5_smc.get("fvgs", [])[-5:]  # last 5 FVGs only
        m5_smc["obs"]  = m5_smc.get("obs", [])[-3:]   # last 3 OBs only
    except Exception:
        m5_smc = {"bias": "neutral", "confidence": 0.0, "fvgs": [], "obs": []}

    # Account risk policy
    try:
        acc = raw.get("account", {})
        perf = load_performance_state()
        policy = assess_account_policy(
            balance=acc.get("balance", 0),
            equity=acc.get("equity", 0),
            free_margin=acc.get("margin_free", 0),
            margin=acc.get("margin", 0),
            daily_pnl=float(perf.get("daily_pnl", 0.0) or 0.0),
            loss_streak=int(perf.get("loss_streak", 0) or 0),
            open_positions=len(raw.get("open_positions", [])),
        )
        # Get merged action for risk budget
        merged_action = merged.get("action", "wait")
        conf = merged.get("confidence", 0)
        if conf > 0.6:
            setup_grade = "A"
        elif conf > 0.35:
            setup_grade = "B"
        else:
            setup_grade = "C"
        risk_budget = recommend_risk_budget(policy, setup_grade) if raw.get("account") else None
    except Exception as e:
        policy = {"regime": "defensive", "risk_multiplier": 0.75, "trade_allowed": False}
        risk_budget = {"trade_allowed": False, "reason": f"error: {e}"}

    # Heartbeat
    hb = check_hermes_status()

    # DEFCON — trade management adaptation from closed trades
    defcon = {}
    try:
        from mt5_xau_defcon import compute_trading_insights
        defcon = compute_trading_insights(performance_state=perf, account=acc)
    except Exception:
        defcon = {"defcon": "green", "entry_allowed": True, "runner_allowed": True}

    # Divergence — multi-TF RSI divergence detection
    divergence = {}
    try:
        from mt5_xau_divergence import multi_tf_divergence
        divergence = multi_tf_divergence(m5, m15, h1)
    except Exception:
        divergence = {"confluence": False, "signal_strength": "none"}

    # Killzone check
    from mt5_xau_smc import active_killzone_session
    kz_name, kz_weight = active_killzone_session(now)
    kz_active = kz_weight > 0

    # Market open check + Macro snapshot
    macro = _collect_macro_snapshot()
    market_open = macro.pop("market_open", False) if macro else False

    # Economic calendar
    calendar = None
    try:
        from mt5_xau_calendar import get_calendar, is_news_risk_active
        calendar = get_calendar(days_ahead=2)
        calendar["news_risk"] = is_news_risk_active()
    except Exception:
        calendar = {"today": [], "tomorrow": [], "upcoming": [], "news_risk": {"risk_active": False}}

    return {
        "analysis_ok": True,
        "session": session,
        "session_detail": {
            "label": sess["label"],
            "volatility": sess["volatility"],
            "liquidity": sess["liquidity"],
            "killzones": [kz["name"] for kz in kzs],
            "high_quality": is_high_quality_window(now_dt),
        },
        "session_risk": session_risk_adjustment(now_dt),
        "timestamp": now.isoformat(),
        "market_open": market_open,
        "killzone": {
            "active": kz_active,
            "name": kz_name,
        },
        "macro": macro if macro else {},
        "calendar": calendar,
        "classic": {
            "bias": classic.get("bias"),
            "price": classic.get("price"),
            "atr": classic.get("atr"),
            "regime": classic.get("quality", {}).get("regime"),
            "alignment": classic.get("quality", {}).get("alignment"),
            "trend_strength": classic.get("quality", {}).get("trend_strength"),
            "value_zone": classic.get("value_zone"),
            "zones": classic.get("zones"),
            "invalidation": classic.get("invalidation"),
            "targets": classic.get("targets"),
        },
        "smc": {
            "bias": smc.get("bias"),
            "confidence": smc.get("confidence"),
            "signal": smc.get("signal"),
            "poi": smc.get("poi", {}),
            "structure": smc.get("structure", {}),
            "h1_structure": smc.get("h1_structure", {}),
            "order_blocks": smc.get("obs", []),
            "h1_order_blocks": smc.get("h1_obs", []),
            "fair_value_gaps": smc.get("fvgs", []),
            "h1_fair_value_gaps": smc.get("h1_fvgs", []),
            "breaker_blocks": smc.get("breaker_blocks", []),
            "rejection_blocks": smc.get("rejection_blocks", []),
            "ote_zone": smc.get("ote_zone"),
            "power_of_three": smc.get("power_of_three"),
            "turtle_soup": smc.get("turtle_soup"),
            "silver_bullet": smc.get("silver_bullet"),
            "session_liquidity": smc.get("session_liquidity"),
            "volume_imbalance": smc.get("volume_imbalance"),
            "premium_discount": smc.get("premium_discount"),
        },
        "merged": {
            "bias": merged.get("bias"),
            "confidence": merged.get("confidence"),
            "action": merged.get("action"),
            "smc_source": merged.get("smc_source"),
        },
        "m5": {
            "bias": m5_classic.get("bias", "neutral"),
            "atr": m5_classic.get("atr", 0),
            "smc_bias": m5_smc.get("bias", "neutral"),
            "smc_confidence": m5_smc.get("confidence", 0.0),
            "fvgs": m5_smc.get("fvgs", []),
            "obs": m5_smc.get("obs", []),
        },
        "account_policy": policy,
        "risk_budget": risk_budget,
        "heartbeat": hb,
        "defcon": {
            "level": defcon.get("defcon", "green"),
            "entry_allowed": defcon.get("entry_allowed", True),
            "runner_allowed": defcon.get("runner_allowed", True),
            "scale_in_allowed": defcon.get("scale_in_allowed", True),
            "risk_override": defcon.get("risk_override"),
            "insights": defcon.get("insights", []),
        },
        "divergence": {
            "m5": divergence.get("m5", {}).get("type", "none"),
            "m15": divergence.get("m15", {}).get("type", "none"),
            "h1": divergence.get("h1", {}).get("type", "none"),
            "confluence": divergence.get("confluence", False),
            "signal_strength": divergence.get("signal_strength", "none"),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Output formatting
# ═══════════════════════════════════════════════════════════════════════════════

def _format_summary(analysis: dict, raw: dict) -> str:
    """Format analysis as Persian-readable summary for Hermes LLM."""
    lines = []
    lines.append("=" * 60)
    lines.append("📊 گزارش لحظه‌ای XAUUSD — برای تصمیم‌گیری Hermes")
    lines.append("=" * 60)

    # ── GATE: if market is closed, produce CONSISTENT minimal output ──
    if analysis.get("market_closed") or not analysis.get("market_open", True):
        acc = raw.get("account", {})
        tick = raw.get("tick") or {}
        lines.append(f"\n📈 بازار: 🔴 بسته | bid={tick.get('bid','?')} ask={tick.get('ask','?')}")
        quote_age = analysis.get("quote_age_sec", 0)
        if quote_age:
            hours = quote_age // 3600
            mins = (quote_age % 3600) // 60
            lines.append(f"   ⏱ آخرین قیمت: {hours}h{mins}m پیش | بازار تعطیل")
        lines.append(f"\n💰 حساب: بالانس=${acc.get('balance',0):,.2f} | ایکوئیتی=${acc.get('equity',0):,.2f} | مارجین آزاد=${acc.get('margin_free',0):,.2f}")
        lines.append(f"\n📌 پوزیشن باز: {'ندارد' if not raw.get('open_positions') else len(raw.get('open_positions', []))}")
        lines.append(f"\n⚠️ بازار بسته است — تحلیل تکنیکال روی داده بسته معتبر نیست.")
        lines.append(f"   تمام بایاس‌ها = neutral, confidence = 0.0")
        lines.append(f"   صبر کنید تا بازار باز شود (دوشنبه)")
        return "\n".join(lines)

    # Account
    acc = raw.get("account", {})
    if acc:
        lines.append(f"\n💰 حساب: بالانس=${acc.get('balance',0):,.2f} | ایکوئیتی=${acc.get('equity',0):,.2f} | مارجین آزاد=${acc.get('margin_free',0):,.2f}")
        profit = acc.get("profit", 0)
        emoji = "🟢" if profit > 0 else "🔴" if profit < 0 else "⚪"
        lines.append(f"   سود/ضرر شناور: {emoji} ${profit:,.2f}")

    # Open positions
    positions = raw.get("open_positions", [])
    if positions:
        lines.append(f"\n📌 پوزیشن‌های باز: {len(positions)}")
        for p in positions:
            pnl_emoji = "🟢" if p["profit"] > 0 else "🔴"
            lines.append(f"   #{p['ticket']} {p['type']} {p['volume']} lot @ {p['open_price']} | فعلی={p['current_price']} | {pnl_emoji} ${p['profit']:,.2f}")
    else:
        lines.append("\n📌 پوزیشن باز: ندارد")

    # Market state
    market = analysis.get("market_open", False)
    tick = raw.get("tick", {})
    price_str = f"bid={tick.get('bid', '?')} ask={tick.get('ask', '?')}" if tick else ""
    lines.append(f"\n📈 بازار: {'🟢 باز' if market else '🔴 بسته'} | {price_str}")
    if tick and tick.get("spread_pips"):
        spread_warn = " ⚠️" if tick.get("spread_pips", 0) > 3 else ""
        lines.append(f"   اسپرد: {tick['spread_pips']} pips{spread_warn} | {'🟢 مجاز' if tick.get('spread_ok') else '🔴 بیش از حد — ورود ممنوع'}")
    lines.append(f"🕐 سشن: {analysis.get('session', '?')} | Killzone: {'🟢 ' + analysis.get('killzone', {}).get('name', '') if analysis.get('killzone', {}).get('active') else '⚪ غیرفعال'}")
    sd = analysis.get("session_detail", {})
    if sd:
        hq = sd.get("high_quality", False)
        sr = analysis.get("session_risk", {})
        risk_label = f" | risk×{sr.get('multiplier', 1.0)}" if sr else ""
        lines.append(f"   {sd.get('label', '?')} | Vol={sd.get('volatility','?')} | Liq={sd.get('liquidity','?')} | {'💎HighQ' if hq else '⚡MidQ'}{risk_label}")

    # Macro
    mx = analysis.get("macro", {})
    if mx:
        lines.append(f"\n─ Macro Context ─")
        dxy = mx.get("dxy", {})
        if dxy:
            lines.append(f"  DXY (proxy): {dxy.get('dxy_value', 0):+.3f}% | {dxy.get('dxy_direction', '?')} | {dxy.get('dxy_strength', '?')}")
        rs = mx.get("risk_sentiment", {})
        if rs:
            lines.append(f"  SPX Risk: {rs.get('spx_change_pct', 0):+.3f}% | {rs.get('risk_mode', '?')}")
        ag = mx.get("silver", {})
        if ag:
            bullish_g = "🐂 gold+" if ag.get("bullish_for_gold") else ""
            lines.append(f"  Silver: {ag.get('xag_change_pct', 0):+.3f}% | {ag.get('xag_direction', '?')} {bullish_g}")
        tv = mx.get("tick_volume", {})
        if tv:
            lines.append(f"  Volume: {tv.get('volume_ratio', '?')}x avg | {'🔊 HIGH' if tv.get('is_high_volume') else 'normal'}")
        htf = mx.get("higher_tf", {})
        if htf:
            h4_t = htf.get("h4", {})
            d1_t = htf.get("d1", {})
            w1_t = htf.get("w1", {})
            lines.append(f"  H4: {h4_t.get('trend','?')} {h4_t.get('zone','?')} | D1: {d1_t.get('trend','?')} {d1_t.get('zone','?')} | W1: {w1_t.get('trend','?')} {w1_t.get('zone','?')}")
            lines.append(f"  Alignment: {htf.get('alignment', '?')}")

    # Economic calendar
    cal = analysis.get("calendar", {})
    if cal:
        news_risk = cal.get("news_risk", {})
        today_evts = cal.get("today", [])
        tomorrow_evts = cal.get("tomorrow", [])
        if today_evts or tomorrow_evts or news_risk.get("risk_active"):
            lines.append(f"\n─ Economic Calendar ─")
            if news_risk.get("risk_active"):
                lines.append(f"  ⚠️ NEWS RISK ACTIVE: {news_risk.get('next_event', '?')} in {news_risk.get('hours_until', '?')}h | gold_impact={news_risk.get('gold_impact', '?')}")
            for e in today_evts[:5]:
                lines.append(f"  📅 TODAY {e.get('iran_time', '?')}: {e.get('title', '?')} [{e.get('impact', '?')}] → {e.get('gold_impact', '?')}")
            for e in tomorrow_evts[:5]:
                lines.append(f"  📅 TMRW {e.get('iran_time', '?')}: {e.get('title', '?')} [{e.get('impact', '?')}] → {e.get('gold_impact', '?')}")

    # Classic
    c = analysis.get("classic", {})
    lines.append(f"\n─ Classic Analysis ─")
    regime = c.get("regime", "?")
    bias_c = c.get("bias", "?")
    lines.append(f"  Bias: {bias_c} | Regime: {regime} | ATR: ${c.get('atr', 0):.2f}")
    lines.append(f"  Alignment: {c.get('alignment', '?')} | Trend: {c.get('trend_strength', 0):.1f}")
    vz = c.get("value_zone") or [0, 0]
    if vz and len(vz) >= 2:
        lines.append(f"  Value Zone: ${vz[0]:.2f} — ${vz[1]:.2f}")

    # SMC
    s = analysis.get("smc", {})
    lines.append(f"\n─ SMC/ICT Analysis ─")
    lines.append(f"  Bias: {s.get('bias', '?')} | Confidence: {s.get('confidence', 0):.3f} | Signal: {s.get('signal', '?')}")
    poi = s.get("poi")
    if poi:
        if isinstance(poi, dict):
            lines.append(f"  POI: grade={poi.get('grade', '?')} | {poi.get('reason', '')}")
        else:
            lines.append(f"  POI: {poi}")
    structure = s.get("structure", {})
    if structure:
        lines.append(f"  Structure: {structure.get('phase', '?')}")
    h1_st = s.get("h1_structure", {})
    if h1_st:
        lines.append(f"  H1 Structure: {h1_st.get('phase', '?')}")

    # Active concepts
    obs_count = len(s.get("order_blocks", []))
    h1_obs_count = len(s.get("h1_order_blocks", []))
    fvgs_count = len(s.get("fair_value_gaps", []))
    h1_fvgs_count = len(s.get("h1_fair_value_gaps", []))
    breakers = len(s.get("breaker_blocks", []))
    ote = s.get("ote_zone")
    pot = s.get("power_of_three", {})
    turtle = s.get("turtle_soup", {})
    sb = s.get("silver_bullet", {})
    lines.append(f"  Concepts: OB={obs_count}, H1_OB={h1_obs_count}, FVG={fvgs_count}, H1_FVG={h1_fvgs_count}, Breaker={breakers}")
    if ote:
        lines.append(f"  OTE Zone: low={ote.get('low','?')} high={ote.get('high','?')}")
    if pot:
        lines.append(f"  PowerOf3: {pot.get('phase','?')}")
    if turtle.get("found"):
        lines.append(f"  🐢 Turtle Soup: FOUND — {turtle.get('direction','?')}")
    if sb.get("active"):
        lines.append(f"  🔫 Silver Bullet: ACTIVE — {sb.get('window','?')}")

    # M5 entry-level view
    mf = analysis.get("m5", {})
    if mf:
        lines.append(f"\n─ M5 Entry View (5min) ─")
        m5_bias = "🟢LONG" if mf.get("bias") == "bullish" else "🔴SHORT" if mf.get("bias") == "bearish" else "⚪NEUTRAL"
        lines.append(f"  Classic bias: {m5_bias} | ATR: ${mf.get('atr', 0):.2f}")
        m5_sb = mf.get("smc_bias", "neutral")
        lines.append(f"  SMC bias: {m5_sb} | Conf: {mf.get('smc_confidence', 0):.3f}")
        fvgs = mf.get("fvgs", [])
        obs = mf.get("obs", [])
        if fvgs or obs:
            lines.append(f"  Active: FVGs={len(fvgs)} OBs={len(obs)}")
        if m5_bias != "⚪NEUTRAL":
            bias_matches = (m5_sb == "bullish" and mf.get("bias") == "bullish") or (m5_sb == "bearish" and mf.get("bias") == "bearish")
            lines.append(f"  {'✅ M5 classic+SMC aligned' if bias_matches else '⚠️ M5 divergence — caution'}")

    # Merged
    m = analysis.get("merged", {})
    lines.append(f"\n─ Merged Decision Hint ─")
    lines.append(f"  Bias: {m.get('bias', '?')} | Confidence: {m.get('confidence', 0):.3f} | Action: {m.get('action', '?')}")

    # DEFCON
    dc = analysis.get("defcon", {})
    if dc:
        dc_level = dc.get("level", "green")
        dc_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(dc_level, "⚪")
        lines.append(f"\n─ DEFCON: {dc_emoji} {dc_level.upper()} ─")
        for ins in dc.get("insights", [])[:3]:
            lines.append(f"  {ins}")

    # Divergence
    dv = analysis.get("divergence", {})
    if dv:
        lines.append(f"\n─ Divergence Detection ─")
        for tf in ["m5", "m15", "h1"]:
            dt = dv.get(tf, "none")
            if dt != "none":
                emoji = "🐂" if "bullish" in dt else "🐻" if "bearish" in dt else "➡️"
                lines.append(f"  {tf.upper()}: {emoji} {dt}")
        if dv.get("confluence"):
            lines.append(f"  {'='*20}")
            lines.append(f"  ⚡ MULTI-TF CONFLUENCE — سیگنال قوی")
        lines.append(f"  Signal: {dv.get('signal_strength', 'none')}")

    # Risk
    p = analysis.get("account_policy", {})
    rb = analysis.get("risk_budget")
    lines.append(f"\n─ Risk & Policy ─")
    lines.append(f"  Mode: {p.get('regime', '?')} | RiskMultiplier: {p.get('risk_multiplier', '?')}")
    if rb:
        lines.append(f"  Risk Budget: trade_allowed={rb.get('trade_allowed')} | risk_usd=${rb.get('risk_usd', 0):.2f}")

    # Heartbeat
    hb = analysis.get("heartbeat", {})
    lines.append(f"\n─ Heartbeat ─")
    if hb:
        lines.append(f"  Mode: {hb.get('mode', '?')} | MinSinceLastHermes: {hb.get('minutes_since_last', '?')}")
        lines.append(f"  DeferToCode: {hb.get('should_defer_to_code', False)} | RiskMult: {hb.get('risk_multiplier', 1.0)}")

    lines.append(f"\n{'─' * 60}")
    lines.append(f"⚠️ تو (Hermes) باید تصمیم بگیری: enter_buy / enter_sell / modify / close / wait")
    lines.append(f"📝 دلیل تصمیمت رو توی decision journal ثبت کن.")
    lines.append(f"🔄 بعد از تصمیم، heartbeat رو آپدیت کن تا سیستم بدونه تو فعالی.")
    lines.append(f"=" * 60)

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def _is_market_closed(raw: dict) -> bool:
    """Check if market is actually closed by looking at tick staleness."""
    tick = raw.get("tick")
    if not tick:
        return True
    tick_time = tick.get("time", 0)
    if tick_time == 0:
        return True
    now_ts = int(_now().timestamp())
    quote_age_sec = now_ts - tick_time
    # If quote is older than 5 minutes, market is effectively closed
    return quote_age_sec > 300


def _closed_market_analysis(raw: dict) -> dict:
    """Produce a minimal analysis when market is closed — no heavy lifting."""
    tick = raw.get("tick") or {}
    acc = raw.get("account") or {}
    now_ts = int(_now().timestamp())
    tick_time = tick.get("time", 0)
    quote_age_sec = now_ts - tick_time if tick_time else 99999
    return {
        "market_open": False,
        "market_closed": True,
        "quote_age_sec": quote_age_sec,
        "analysis_ok": True,
        "error": None,
        "classic": {"bias": "neutral", "regime": "closed", "atr": 0},
        "smc": {"bias": "neutral", "confidence": 0, "signal": "closed"},
        "merged": {"bias": "neutral", "confidence": 0, "agreement": "market_closed"},
        "macro": {"dxy": {}, "risk_sentiment": {}, "silver": {}, "higher_tf": {}},
        "session": "weekend",
        "killzone": {"active": False, "name": ""},
        "session_detail": {"label": "Market Closed", "volatility": "none", "liquidity": "none", "high_quality": False},
        "session_risk": {"multiplier": 0.0},
        "calendar": {"news_risk": {"risk_active": False}},
        "divergence": {"signal": "none", "confluence": 0},
        "defcon": {"level": "GREEN"},
    }


def collect(now: datetime | None = None) -> tuple[dict, dict, str]:
    """Main entry point. Returns (raw, analysis, summary)."""
    from mt5_xau_heartbeat import record_heartbeat_ping

    if now is None:
        now = _now()

    # Always ping heartbeat
    try:
        record_heartbeat_ping()
    except Exception:
        pass

    raw = _collect_raw_data()

    # ── GATE: if market is closed, skip ALL heavy analysis ──
    if _is_market_closed(raw):
        analysis = _closed_market_analysis(raw)
        summary = _format_summary(analysis, raw)
        return raw, analysis, summary

    analysis = _run_analysis(raw, now)
    summary = _format_summary(analysis, raw)

    return raw, analysis, summary


if __name__ == "__main__":
    # When run standalone: print summary + JSON block for LLM
    _, analysis, summary = collect()
    print(summary)
    print("\n\n<!-- JSON_CONTEXT_START -->")
    print(json.dumps(analysis, indent=2, ensure_ascii=False, default=str))
    print("<!-- JSON_CONTEXT_END -->")
