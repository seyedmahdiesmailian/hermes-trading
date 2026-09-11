from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def evaluate_macro_filter(calendar: dict | None, now: str | datetime, blackout_minutes: int = 30) -> dict:
    current = _parse(now) if isinstance(now, str) else now
    cal = calendar or {}
    # b30 FAIL CLOSED: 'unavailable' means we CANNOT SEE the news, not that
    # there is none. The old shape ({'source':'unavailable','events':[]})
    # scored allowed=True — a dead calendar disabled the blackout gate on
    # both entry paths for as long as the failure lasted.
    if cal.get("unavailable") or str(cal.get("source", "")).lower() == "unavailable":
        return {"allowed": False, "reason": "calendar_unavailable", "events": []}
    events = cal.get("events", [])
    relevant = []
    for event in events:
        if str(event.get("impact", "")).lower() != "high":
            continue
        # b211(a): same null-currency skip class as legacy_guards — a
        # currency: null event became "NONE" and passed the blackout.
        # Read country as the fallback the fetcher normalizes from, then ""
        # (unknown = treated as gold-relevant). Only ever fires MORE blocks.
        currency = str(event.get("currency") or event.get("country") or "").upper()
        if currency not in {"USD", "XAU", "GOLD", ""}:
            continue
        try:
            # economic_calendar emits 'date' (full ISO with offset); older
            # feeds used 'timestamp'. Read both — before this, KeyError made
            # every event skip and the blackout could never fire.
            event_time = _parse(str(event["date"] if event.get("date") else event["timestamp"]))
        except (KeyError, TypeError, ValueError):
            continue
        if abs(event_time - current) <= timedelta(minutes=blackout_minutes):
            relevant.append(event)
    if relevant:
        return {"allowed": False, "reason": "high_impact_news_blackout", "events": relevant}
    return {"allowed": True, "reason": None, "events": []}


def apply_macro_guard(proposal: dict | None, macro: dict) -> dict | None:
    if proposal is None or macro.get("allowed", True):
        return proposal
    guarded = dict(proposal)
    guarded["blocked"] = True
    guarded["reason"] = macro.get("reason", "macro_filter_block")
    guarded["macro_events"] = macro.get("events", [])
    # b170: auto_executor Check 7 vetoes on 'blocked_by_macro', but NOBODY
    # ever wrote that key (measured 2026-09-09: grep over the whole repo —
    # its only reader was the check itself, plus b132's source pin). The
    # veto really lands via 'blocked' + Check 1. Set the flag here too so
    # Check 7 becomes a live second net and b132's pin is honest.
    # Tightening-neutral: adds a veto path, never removes one.
    guarded["blocked_by_macro"] = True
    return guarded
