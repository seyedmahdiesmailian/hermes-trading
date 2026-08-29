"""Shared market-hours guard for ALL execution paths.

XAUUSD trades ~Sun 23:00 UTC → Fri 22:00 UTC. This used to live only inside
auto_executor.evaluate_proposal (the plan-driven path); the signal path called
execute_trade() directly and could fire orders into a closed market
(broker retcode 10018 spam / rejected orders on weekends).
"""
from __future__ import annotations

import datetime as dt


def is_market_open(now: dt.datetime | None = None) -> bool:
    """True when XAUUSD should be tradeable (Sun 23:00 UTC → Fri 22:00 UTC)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    wd = now.weekday()          # Mon=0 … Sun=6
    if wd == 5:                 # Saturday
        return False
    if wd == 6 and now.hour < 23:   # Sunday before 23:00 UTC
        return False
    if wd == 4 and now.hour >= 22:  # Friday after 22:00 UTC
        return False
    return True


def closed_reason(now: dt.datetime | None = None) -> str:
    return "" if is_market_open(now) else "market_closed"
