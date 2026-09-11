"""Time-exit & news-lock management — migrated from legacy priority order.

Legacy source: skills/trading/autonomous-trading-agent-design/references/
architecture-v5-modules.md → "Trade Management Priority Order":

    1. news_lock   (safety — tighten SL before high-impact event)
    2. time_exit   (safety — exit positions open too long)
    3. partial_tp  (profit)
    4. trail       (profit)
    5. move_be     (risk)
    6. hold

This module implements 1 & 2 which were lost in the rebuild. The existing
engines/trade_management.py covers 3-6; hermes_runtime merges both outputs
with this priority order (news_lock > time_exit > legacy chain).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

MAX_POSITION_AGE_HOURS = 36        # XAUUSD swing context; stale = exit
NEWS_LOCK_MINUTES_BEFORE = 30      # tighten SL 30 min before high-impact news
NEWS_TIGHTEN_ATR_MULT = 0.5        # new SL distance = 0.5 * ATR (from current price)


def is_news_lock(management: dict | None) -> bool:
    """b167: the ONE predicate for "this move_stop_to_breakeven is a NEWS LOCK,
    not the real post-TP1 breakeven".

    evaluate_news_lock REUSES the action name because that is the SL-modify
    executor's verb. Every caller that marks 'breakeven happened' on seeing
    move_stop_to_breakeven must therefore exclude the lock — breakeven_active
    suppresses the real BE branch (`if filled and not breakeven_active`)
    forever, so a pre-TP1 lock that claimed the flag leaves the runner riding
    its original stop through the give-back. b32 wrote the exclusion inline in
    position_daemon; hermes_runtime's fallback path shipped without it (the
    b109/b111 drift class, on a safety flag). Both callers now use THIS.
    """
    if not management:
        return False
    return str(management.get("reason", "")).startswith("news_lock")


def _parse(ts: str | datetime) -> datetime:
    dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def evaluate_time_exit(trade: dict, now: datetime | None = None) -> dict | None:
    """Position open too long → close. Returns action dict or None."""
    opened = trade.get("opened_at") or trade.get("time")
    if not opened:
        return None
    try:
        age = (_parse(now or datetime.now(timezone.utc)) - _parse(opened)).total_seconds() / 3600
    except Exception:
        return None
    if age >= MAX_POSITION_AGE_HOURS:
        return {
            "action": "close_trade_early",
            "reason": f"time_exit_{age:.0f}h",
            "priority": 2,
            "at": (now or datetime.now(timezone.utc)).isoformat(),
        }
    # warn-level: position approaching stale (used in reports, no action)
    if age >= MAX_POSITION_AGE_HOURS * 0.75:
        return {
            "action": "hold",
            "reason": f"time_exit_warning_{age:.0f}h",
            "priority": 9,
            "at": (now or datetime.now(timezone.utc)).isoformat(),
        }
    return None


def evaluate_news_lock(
    trade: dict,
    market_price: float,
    macro_calendar: dict | None,
    now: datetime | None = None,
) -> dict | None:
    """High-impact news within window → tighten SL to 0.5 ATR. None = no lock.

    Accepts either a calendar dict ({events: [...]}) or a raw event list.
    Event timestamps are read from 'timestamp' | 'datetime_utc' | 'date' |
    'date'+'time' (ForexFactory gives ISO dates with offset, time=None).

    b31 SHAPE FIX — this guard was mathematically DEAD in production: the
    only calendar it ever receives is plan.context.macro.calendar, written
    from get_upcoming_events(), whose shape is
    {'source','high_impact':[...],'medium_impact':[...],'total_events',...}
    — there is NO 'events' key. The old lookup chain fell through to the
    dict itself, `isinstance(events, list)` failed, and the guard returned
    None for ANY input. Proof: scripts/probe_news_lock.py feeds a FOMC
    event 10 minutes away (dead center of the 30-min window) in the
    production shape → None; in the raw {'events': [...]} shape → correct
    lock. 'high_impact' is now read first, pinned by a regression test.
    """
    if not macro_calendar:
        return None
    now = now or datetime.now(timezone.utc)
    if isinstance(macro_calendar, dict):
        events = (macro_calendar.get("high_impact")
                  or macro_calendar.get("events")
                  or macro_calendar.get("calendar_summary")
                  or macro_calendar)
    else:
        events = macro_calendar  # raw list of events
    if isinstance(events, dict):
        events = events.get("events")
    if not isinstance(events, list):
        return None
    side_buy = str(trade.get("side", trade.get("type", ""))).upper() in ("BUY", "0")

    for ev in events:
        try:
            if str(ev.get("impact", "")).lower() != "high":
                continue
            # b211(a): two-arg .get() only defaults on a MISSING key — a feed
            # that emits currency: null gave str(None)="NONE", in neither the
            # gold set nor any country code, so a real high-impact FOMC row
            # was silently skipped and the lock never fired. The `or` chain
            # (the fetcher's own normalization at economic_calendar:125) is
            # strictly more protective: null/empty fall through to country
            # and finally "" = unknown = assume gold-relevant.
            cur = str(ev.get("currency") or ev.get("country") or "").upper()
            if cur not in {"USD", "XAU", "GOLD", ""}:
                continue
            t_raw = (ev.get("timestamp") or ev.get("datetime_utc")
                     or ev.get("date") or ev.get("time"))
            if not t_raw:
                continue
            et = _parse(str(t_raw))
            delta_min = (et - now).total_seconds() / 60.0
            if 0 < delta_min <= NEWS_LOCK_MINUTES_BEFORE:
                atr = float(trade.get("atr", 0) or 0) or 5.0
                new_sl_dist = NEWS_TIGHTEN_ATR_MULT * atr
                entry = float(trade.get("entry_price") or trade.get("price_open") or market_price)
                new_sl = market_price + new_sl_dist if not side_buy else market_price - new_sl_dist
                old_sl = float(trade.get("sl") or 0)
                # only tighten in the protective direction, never loosen
                protective = (
                    (side_buy and new_sl > old_sl) or ((not side_buy) and (old_sl == 0 or new_sl < old_sl))
                )
                if protective and abs(market_price - new_sl) > 1.0:
                    return {
                        "action": "move_stop_to_breakeven",  # reuse SL-modify executor
                        "new_sl": round(new_sl, 2),
                        "reason": f"news_lock:{ev.get('title', 'high_impact')}_{delta_min:.0f}min",
                        "priority": 1,
                        "at": now.isoformat(),
                    }
        except Exception:
            continue
    return None
