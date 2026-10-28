"""
Pre-Session Analysis — runs before London Open to prepare the trading day.

What it does:
  1. Collect H4/D1/W1 SMC levels (key POIs, OBs, breakers)
  2. Collect macro context (DXY, SPX, silver)
  3. Check economic calendar for today's events
  4. Generate scenario plan: bullish case, bearish case, neutral case
  5. Write plan to trading/xau_plan/presession_YYYYMMDD.json

Run: 30 min before London Open daily
  - Summer: Iran 09:00 (London 06:30 GMT)
  - Winter: Iran 10:00 (London 07:30 GMT)
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

PLAN_DIR = Path("/home/ai/hermes-trading/data/trading/xau_plan")
SCRIPTS = Path("/home/ai/hermes-trading/scripts")
sys.path.insert(0, str(SCRIPTS))

IRAN_OFFSET = timedelta(hours=3, minutes=30)


def collect_macro() -> dict:
    """Get macro context via MT5."""
    import MetaTrader5 as mt5
    from mt5_xau_macro import build_macro_snapshot
    if not mt5.initialize():
        return {"error": "mt5_init_failed"}
    try:
        return build_macro_snapshot(mt5)
    finally:
        mt5.shutdown()


def collect_calendar() -> dict:
    """Get today's economic calendar."""
    try:
        from mt5_xau_calendar import get_calendar
        return get_calendar(days_ahead=1)
    except Exception as e:
        return {"error": str(e)}


def collect_key_levels() -> dict:
    """Get SMC key levels from H4/D1/W1."""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        return {"error": "mt5_init_failed"}
    try:
        from mt5_xau_smc import smc_analyse

        levels = {}
        for tf_name, tf_const in [("H4", mt5.TIMEFRAME_H4), ("D1", mt5.TIMEFRAME_D1), ("W1", mt5.TIMEFRAME_W1)]:
            result = smc_analyse("XAUUSD", tf_const, lookback_bars=100)
            levels[tf_name] = {
                "bias": result.get("bias"),
                "confidence": result.get("confidence"),
                "trend": result.get("trend"),
                "poi": result.get("poi"),
                "key_levels": result.get("key_levels", []),
                "ob_levels": result.get("ob_levels", []),
                "liquidity_levels": result.get("liquidity_levels", []),
            }
        return levels
    except Exception as e:
        return {"error": str(e)}
    finally:
        mt5.shutdown()


def generate_scenarios(
    htf_levels: dict,
    macro: dict,
    calendar: dict,
) -> dict:
    """Generate bullish, bearish, neutral scenarios from collected data."""
    alignment = macro.get("higher_tf", {}).get("alignment", "neutral")

    dxy = macro.get("dxy", {})
    risk = macro.get("risk_sentiment", {})
    silver = macro.get("silver", {})

    # Determine structural bias from HTF alignment
    structural_bias = "neutral"
    if alignment == "bullish_all":
        structural_bias = "bullish"
    elif alignment == "bearish_all":
        structural_bias = "bearish"
    elif "bullish" in alignment:
        structural_bias = "bullish"
    elif "bearish" in alignment:
        structural_bias = "bearish"

    # Compile scenarios
    scenarios = {
        "structural_bias": structural_bias,
        "dxy_signal": "gold_bullish" if dxy.get("dxy_direction") == "down" else "gold_bearish" if dxy.get("dxy_direction") == "up" else "neutral",
        "risk_sentiment": risk.get("risk_mode", "risk_off"),
        "silver_confirms": silver.get("bullish_for_gold", False),

        "bullish_scenario": {
            "trigger": "",
            "entry_zone_low": None,
            "entry_zone_high": None,
            "targets": [],
            "invalidation": None,
            "confidence": 0.5,
        },
        "bearish_scenario": {
            "trigger": "",
            "entry_zone_low": None,
            "entry_zone_high": None,
            "targets": [],
            "invalidation": None,
            "confidence": 0.5,
        },
        "neutral_scenario": {
            "description": "range-bound, wait for breakout",
            "range_low": None,
            "range_high": None,
            "confidence": 0.5,
        },
    }

    # Build bullish scenario from HTF levels
    d1 = htf_levels.get("D1", {})
    h4 = htf_levels.get("H4", {})

    # Key levels for scenarios
    buy_ob = None
    sell_ob = None
    for ob in h4.get("ob_levels", []):
        if ob.get("type") == "buy_ob":
            buy_ob = ob.get("price")
        elif ob.get("type") == "sell_ob":
            sell_ob = ob.get("price")

    if structural_bias == "bullish":
        scenarios["bullish_scenario"]["trigger"] = "Pullback to D1/H4 OB + FVG + macro confirmed"
        scenarios["bullish_scenario"]["entry_zone_low"] = buy_ob
        scenarios["bullish_scenario"]["entry_zone_high"] = buy_ob + 10.0 if buy_ob else None
        scenarios["bullish_scenario"]["targets"] = ["previous high", "W1 resistance"]
        scenarios["bullish_scenario"]["invalidation"] = "Below D1 swing low"
        scenarios["bullish_scenario"]["confidence"] = 0.75 if silver.get("bullish_for_gold") else 0.60

        scenarios["bearish_scenario"]["trigger"] = "Only if news/dxy reversal confirmed"
        scenarios["bearish_scenario"]["entry_zone_low"] = sell_ob
        scenarios["bearish_scenario"]["entry_zone_high"] = sell_ob - 10.0 if sell_ob else None
        scenarios["bearish_scenario"]["confidence"] = 0.30

    elif structural_bias == "bearish":
        scenarios["bearish_scenario"]["trigger"] = "Rally to D1/H4 OB + FVG + macro confirmed"
        scenarios["bearish_scenario"]["entry_zone_low"] = sell_ob
        scenarios["bearish_scenario"]["entry_zone_high"] = sell_ob + 10.0 if sell_ob else None
        scenarios["bearish_scenario"]["targets"] = ["previous low", "W1 support"]
        scenarios["bearish_scenario"]["invalidation"] = "Above D1 swing high"
        scenarios["bearish_scenario"]["confidence"] = 0.75 if not silver.get("bullish_for_gold") else 0.60

        scenarios["bullish_scenario"]["trigger"] = "Only if news/dxy reversal confirmed"
        scenarios["bullish_scenario"]["confidence"] = 0.30

    else:
        # Neutral/range
        scenarios["neutral_scenario"]["confidence"] = 0.70
        scenarios["bullish_scenario"]["trigger"] = "Breakout above range high"
        scenarios["bullish_scenario"]["confidence"] = 0.45
        scenarios["bearish_scenario"]["trigger"] = "Breakdown below range low"
        scenarios["bearish_scenario"]["confidence"] = 0.45

    # Add calendar events summary
    today_events = calendar.get("today", [])
    scenarios["news_today"] = [
        {"time": e.get("iran_time", "?"), "title": e.get("title", "?"),
         "impact": e.get("impact", "?"), "gold_impact": e.get("gold_impact", "?")}
        for e in today_events
    ]

    return scenarios


def run_presession_analysis() -> bool:
    """Main entry: collect data, generate scenarios, write plan."""
    now = datetime.now()
    iran_now = now + IRAN_OFFSET

    print(f"═══ Pre-Session Analysis ═══")
    print(f"Time (Iran): {iran_now.strftime('%Y-%m-%d %H:%M')}")
    print(f"Day: {iran_now.strftime('%A')}")

    # Collect all data
    print("\n📊 Collecting macro...")
    macro = collect_macro()

    print("📅 Collecting calendar...")
    calendar = collect_calendar()

    print("📈 Collecting key levels (H4/D1/W1)...")
    levels = collect_key_levels()

    # Generate scenarios
    print("🎯 Generating scenarios...")
    scenarios = generate_scenarios(levels, macro, calendar)

    # Build full plan
    plan = {
        "type": "presession",
        "created_at": now.isoformat(),
        "iran_time": iran_now.isoformat(),
        "day_of_week": iran_now.strftime("%A"),
        "macro": macro,
        "calendar_summary": calendar.get("today", [])[:10],
        "htf_levels": levels,
        "scenarios": scenarios,
    }

    # Write plan
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    plan_file = PLAN_DIR / f"presession_{iran_now.strftime('%Y%m%d')}.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False, default=str)

    # Also write as current plan
    current_file = PLAN_DIR / "current_presession.json"
    with open(current_file, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n✅ Pre-session plan written to: {plan_file}")
    print(f"✅ Current plan: {current_file}")

    # Print summary
    s = scenarios
    print(f"\n═══ Summary ═══")
    print(f"Structural Bias: {s['structural_bias']}")
    print(f"DXY Signal: {s['dxy_signal']}")
    print(f"Risk Mode: {s['risk_sentiment']}")
    print(f"Silver Confirms: {s['silver_confirms']}")

    news_today = s.get("news_today", [])
    if news_today:
        print(f"\nToday's News ({len(news_today)} events):")
        for n in news_today[:5]:
            print(f"  {n['time']}: {n['title']} [{n['impact']}] → {n['gold_impact']}")

    if s["bullish_scenario"]["confidence"] >= 0.5:
        b = s["bullish_scenario"]
        print(f"\n🐂 Bullish: trigger={b['trigger']} confidence={b['confidence']}")
        if b["entry_zone_low"]:
            print(f"   Entry zone: {b['entry_zone_low']}-{b['entry_zone_high']}")

    if s["bearish_scenario"]["confidence"] >= 0.5:
        ber = s["bearish_scenario"]
        print(f"🐻 Bearish: trigger={ber['trigger']} confidence={ber['confidence']}")

    print(f"⚪ Neutral: confidence={s['neutral_scenario']['confidence']}")

    return True


if __name__ == "__main__":
    success = run_presession_analysis()
    sys.exit(0 if success else 1)
