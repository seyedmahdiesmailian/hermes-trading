"""b70 — Signal LIMIT orders: park a good signal at its entry price.

Problem (user, 2026-09-04): a channel posts BUY @ 4472 while price is 4484.
The signal is still VALID — price simply hasn't reached the entry yet. The
old behaviour skipped it entirely (staleness guard). This module turns that
skip into a pending BUY_LIMIT at the exact entry, then watches it:

  * filled            -> alert (the position itself is managed by the
                         normal management path, same as market entries)
  * TTL expired       -> cancel + alert (a 4h-old signal is dead)
  * kill-switch halt  -> cancel all pending + alert
  * market closed     -> cancel before the close (a pending order waking up
                         on Monday gap is not the trade we signed up for)

Safety model mirrors the market path: placement only happens AFTER
evaluate_proposal passed every gate; the lot comes from our own risk model
(capped by the channel's lot); at most HERMES_PENDING_MAX (default 2)
pending orders may live at once; distance from current price is capped at
1R by the caller.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from engines import paths

__all__ = ["place_signal_limit", "watch_pending", "load_pending", "save_pending"]

_last_check = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def pending_enabled() -> bool:
    return os.getenv("HERMES_SIGNAL_PENDING", "true").lower() not in {"0", "false", "no"}


def pending_ttl_min() -> float:
    try:
        return max(15.0, float(os.getenv("HERMES_PENDING_TTL_MIN", "240")))
    except ValueError:
        return 240.0


def pending_max() -> int:
    try:
        return max(1, int(os.getenv("HERMES_PENDING_MAX", "2")))
    except ValueError:
        return 2


def load_pending() -> list[dict]:
    p = paths.pending_state()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def save_pending(items: list[dict]):
    paths.write_json_atomic(paths.pending_state(), items)


def place_signal_limit(bridge, command: dict, symbol: str = "XAUUSD",
                       alert=None) -> dict:
    """Place a BUY_LIMIT/SELL_LIMIT for a vetted signal command.

    Returns {'ok': bool, 'ticket': int|None, 'error': str|None}.
    Never raises — a failed placement must degrade to the old skip path.
    """
    def _say(msg: str):
        if alert:
            try:
                alert(msg)
            except Exception:
                pass

    side = str(command.get("side", "")).upper()
    entry = float(command.get("entry") or 0)
    sl = float(command.get("sl") or 0)
    tp = float(command.get("tp") or 0)
    lot = float(command.get("lot") or 0)
    if side not in {"BUY", "SELL"} or entry <= 0 or sl <= 0 or tp <= 0 or lot <= 0:
        return {"ok": False, "ticket": None, "error": "invalid_command"}

    items = load_pending()
    # one pending per (side, entry) — a channel repeating the same level
    # must not stack two limit orders at the same price
    if any(abs(float(i.get("entry") or 0) - entry) < 0.01
           and str(i.get("side", "")).upper() == side for i in items):
        return {"ok": False, "ticket": None, "error": "duplicate_pending"}
    if len(items) >= pending_max():
        return {"ok": False, "ticket": None,
                "error": f"pending_cap_{pending_max()}"}

    try:
        res = bridge.send_pending(side=side, lot=lot, symbol=symbol,
                                  price=entry, sl=sl, tp=tp) or {}
    except Exception as e:
        return {"ok": False, "ticket": None, "error": f"bridge:{str(e)[:120]}"}

    ticket = res.get("ticket")
    if not (res.get("ok") and ticket):
        return {"ok": False, "ticket": None,
                "error": str(res.get("error") or res.get("comment")
                             or "broker_rejected")[:160]}

    items.append({
        "ticket": int(ticket),
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "lot": lot,
        "symbol": symbol,
        "placed_at": _now().isoformat(),
        "ttl_min": pending_ttl_min(),
        "source": "signal",
    })
    save_pending(items)
    _say(f"🕒 LIMIT گذاشته شد\n{side} {symbol} @ {entry}\n"
         f"SL: {sl} | TP: {tp} | lot: {lot}\n"
         f"تا رسیدن قیمت به نقطه ورود منتظر می‌مانم "
         f"(حداکثر {pending_ttl_min():.0f} دقیقه)")
    return {"ok": True, "ticket": int(ticket), "error": None}


def watch_pending(bridge, alert=None, kill_halted: bool = False,
                  market_open: bool = True) -> list[dict]:
    """Daemon tick: reconcile tracked pending orders with the broker.

    Called every loop of signal_daemon. Returns list of events (for logging).
    """
    def _say(msg: str):
        if alert:
            try:
                alert(msg)
            except Exception:
                pass

    items = load_pending()
    if not items:
        return []

    events: list[dict] = []
    now = _now()

    # throttle broker reconciliation: 15s is plenty for limit-order fills,
    # and the daemon loop ticks every 2s — don't hammer the bridge
    global _last_check
    if (now - _last_check).total_seconds() < 15 and not kill_halted and market_open:
        return []
    _last_check = now

    # kill-switch or market closed -> cancel everything we parked
    if kill_halted or not market_open:
        for it in items:
            _cancel_quiet(bridge, it["ticket"])
        reason = "kill_switch" if kill_halted else "market_closed"
        _say(f"🧹 تمام سفارش‌های حد لغو شد ({reason}) — {len(items)} مورد")
        save_pending([])
        return [{"event": "cancel_all", "reason": reason, "count": len(items)}]

    try:
        orders_resp = bridge.get_orders() or {}
        live_ids = set()
        for o in (orders_resp.get("data") or []):
            try:
                live_ids.add(int(o.get("ticket") or o.get("order_id") or 0))
            except (TypeError, ValueError):
                pass
    except Exception:
        # transient bridge error: do nothing this tick, never cancel blindly
        return []

    still_alive: list[dict] = []
    for it in items:
        tkt = int(it["ticket"])
        age_min = (now - datetime.fromisoformat(it["placed_at"])).total_seconds() / 60
        if tkt in live_ids:
            if age_min > float(it.get("ttl_min") or pending_ttl_min()):
                _cancel_quiet(bridge, tkt)
                _say(f"⌛ LIMIT منقضی شد (بدون فیول)\n"
                     f"{it['side']} {it['symbol']} @ {it['entry']} — لغو شد")
                events.append({"event": "ttl_cancel", "ticket": tkt})
            else:
                still_alive.append(it)
            continue

        # order no longer active: filled, or cancelled/expired at broker side
        filled = _was_filled(bridge, tkt, it.get("symbol", "XAUUSD"))
        if filled:
            _say(f"🎯 LIMIT فیول شد — پوزیشن باز شد\n"
                 f"{it['side']} {it['symbol']} @ {filled.get('price') or it['entry']}\n"
                 f"SL: {it['sl']} | TP: {it['tp']} | lot: {it['lot']}")
            events.append({"event": "filled", "ticket": tkt})
        else:
            _say(f"⚠️ LIMIT از لیست بروکر حذف شد و فیول نشده بود — نادیده گرفته شد\n"
                 f"{it['side']} {it['symbol']} @ {it['entry']}")
            events.append({"event": "vanished", "ticket": tkt})

    save_pending(still_alive)
    return events


def _was_filled(bridge, ticket: int, symbol: str) -> dict | None:
    """Look for an IN deal referencing the pending order ticket.

    MT5 DEAL_ENTRY: IN=0, OUT=1 (int from the live bridge). Accepting only
    entry==0 means a partial-close OUT deal can never masquerade as a fill.
    """
    try:
        resp = bridge.get_history_deals(symbol=symbol, days=2) or {}
        for d in (resp.get("data") or []):
            if int(d.get("order") or 0) != ticket:
                continue
            ent = d.get("entry")
            if str(ent).strip().lower() in {"0", "in", "deal_entry_in"}:
                return d
    except Exception:
        pass
    return None


def _cancel_quiet(bridge, ticket: int):
    try:
        bridge.cancel_order(ticket)
    except Exception:
        pass
