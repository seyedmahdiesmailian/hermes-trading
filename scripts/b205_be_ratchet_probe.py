#!/usr/bin/env python3
"""b205 probe — can the post-TP1 breakeven move LOOSEN a stop that the
news-lock guard already tightened?

Root-cause read (2026-09-10): b202 ratcheted the `trail_stop` branch of
engines/trade_management.evaluate_trade_management against the live-parity
funnel's `cand > t["sl"]` rule (engines/backtest.py). But the
`move_stop_to_breakeven` branch (line ~270) compares `new_sl` only against
the MARKET (b44/b52 gap guard) — never against the CURRENT stop. A
`protective`-ratchated move_stop_to_breakeven does exist in ONE caller
(engines/legacy_guards.evaluate_news_lock), which proves the codebase
already knows this move must never loosen; BE branch just never got the
same guard.

Realistic BUY sequence this probe replays through the live evaluator:
  entry 4430, sl 4400 (risk 30), grade 2, momentum 0.7 (lock = 0.15R)
  1. high-impact USD news in 20 min, price 4488 -> news lock SL to 4485
     (legacy_guards, protective branch fires: 4485 > 4400)
  2. price reaches TP1 4495, partial fills, `filled` non-empty
  3. next cycle at price 4492: BE branch proposes entry+0.15R = 4434.5
     -> 4434.5 < 4485: the broker-accepted news lock is GIVEN BACK by
     50.5 dollars ($30.3 of the locked profit refunded to the stop).
The probe calls the REAL functions (no re-implementation) and asks the
executor what it would send to bridge.modify_position.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.trade_management import evaluate_trade_management   # noqa: E402
from engines.legacy_guards import evaluate_news_lock, is_news_lock  # noqa: E402

now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
trade = {
    "side": "BUY", "entry_price": 4430.0, "sl": 4400.0,
    "tp_levels": [4495.0, 4560.0], "filled_tp_levels": [],
    "grade": 2, "momentum_strength": 0.7, "atr": 6.0,
    "breakeven_active": False, "thesis_valid": True,
}
cal = {"source": "ff", "high_impact": [
    {"impact": "high", "currency": "USD", "title": "FOMC",
     "timestamp": (now + timedelta(minutes=20)).isoformat()}]}

# step 1: the news lock tightens the stop (this is what live does pre-TP1)
lock = evaluate_news_lock(dict(trade), market_price=4488.0,
                          macro_calendar=cal, now=now)
print("news_lock:", None if not lock else
      {"action": lock["action"], "new_sl": lock["new_sl"],
       "reason": lock["reason"][:40], "is_news_lock": is_news_lock(lock)})
assert lock and lock["action"] == "move_stop_to_breakeven", "lock did not fire"
trade["sl"] = lock["new_sl"]                      # broker accepted it

# step 2: TP1 hit -> partial fills; the executor marks it filled, NOT
# breakeven_active (is_news_lock correctly suppresses that flag — b167)
trade["filled_tp_levels"] = [4495.0]

# step 3: the BE branch runs against the tightened stop
mgmt = evaluate_trade_management(trade, market_price=4492.0, now=now)
cur = trade["sl"]
print("BE proposal:", {"action": mgmt.get("action"),
                       "new_sl": mgmt.get("new_sl"),
                       "current_sl": cur,
                       "reason": mgmt.get("reason")})
if mgmt.get("action") == "move_stop_to_breakeven":
    loosens = mgmt["new_sl"] < cur               # BUY: lower SL = looser
    print("VERDICT:", "BUG — BE LOOSENS the accepted news lock by $%.1f"
          % (cur - mgmt["new_sl"]) if loosens else "ok (BE tightens)")
else:
    print("VERDICT:", "no BE move proposed — ratchet already present?")