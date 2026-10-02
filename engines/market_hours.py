"""Shared market-hours guard for ALL execution paths.

XAUUSD trades Sun 22:00 UTC -> Fri 21:00 UTC. This used to live only inside
auto_executor.evaluate_proposal (the plan-driven path); the signal path called
execute_trade() directly and could fire orders into a closed market
(broker retcode 10018 spam / rejected orders on weekends).

BOUNDARY (b93 evidence, data/backtest/b93_market_hours_gate.json): the first
real bar of each of 7 measured weeks lands at Sun 22:00:01 UTC and the last at
Fri 20:45 UTC, i.e. the broker opens Sun 22:00 and closes Fri 21:00. The gate
previously read Sun 23:00 / Fri 22:00 - 1h conservative at the open (blocking
a live hour) and 1h permissive at the close (allowing entries into an already
closed market). Tightened to the measured boundary 2026-10-02 by direction.
"""
from __future__ import annotations

import datetime as dt

# Single source of truth for the weekly session (UTC).
WEEKLY_OPEN = (6, 22, 0)   # Sunday 22:00 UTC  (weekday: Mon=0 ... Sun=6)
WEEKLY_CLOSE = (4, 21, 0)  # Friday 21:00 UTC


def is_market_open(now: dt.datetime | None = None) -> bool:
    """True when XAUUSD should be tradeable (Sun 22:00 UTC -> Fri 21:00 UTC).

    Naive `now` is read as UTC.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    wd = now.weekday()          # Mon=0 ... Sun=6
    if wd == 5:                 # Saturday: never open
        return False
    if wd == 6:                 # Sunday: open from 22:00 UTC
        return now.hour * 60 + now.minute >= 22 * 60
    if wd == 4:                 # Friday: close at 21:00 UTC
        return now.hour * 60 + now.minute < 21 * 60
    return True                 # Monday-Thursday


def closed_reason(now: dt.datetime | None = None) -> str:
    return "" if is_market_open(now) else "market_closed"
