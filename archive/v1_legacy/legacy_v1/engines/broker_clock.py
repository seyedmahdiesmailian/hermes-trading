"""b35 — shared broker-clock calibration between the two time_exit consumers.

Why: MT5 reports position open times as epoch seconds on the BROKER SERVER
clock (~UTC+3 for CapitalXtend), not UTC. position_daemon estimates the
offset from its live 5s tick stream (NTP-style min-delay, b32) and de-rotates
before feeding evaluate_time_exit. hermes_runtime's FALLBACK management path
(the only manager when the watchdog is dead) cannot re-measure: a 15-min
cycle has no consecutive polls to prove the stream is live. So the daemon
PUBLISHES its calibration here and the runtime READS it.

Direction of every degradation in this file is deliberate: no calibration →
the runtime falls back to the watchdog's detection time, which is LATER than
the true open → the position looks OLDER → time_exit fires EARLY, never late.
An early 36h exit costs a little optionality; a late one leaves an unmanaged
stale trade in the market.

File shape (data/xau_plan/broker_clock.json):
    {"offset_sec": 10800.0, "measured_at": "<utc iso>", "source": "position_daemon"}
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from engines import paths

# Every FX broker server timezone fits inside ±14h of UTC; anything outside
# is a broken stamp, not a timezone (same bound position_daemon uses to
# reject implausible tick samples).
SANITY_SEC = 14 * 3600
# A calibration older than this says the daemon has been dead or starved of
# live ticks since then — the runtime must not trust it.
DEFAULT_MAX_AGE_SEC = 24 * 3600
# Rewrites are throttled: measured_at doubles as a liveness stamp for the
# reader's TTL, so a stable-but-alive daemon still refreshes it periodically.
MIN_REWRITE_INTERVAL_SEC = 300.0
# A drift smaller than this is tick-truncation noise, not a new calibration.
REWRITE_DRIFT_SEC = 1.0


def _parse_iso(ts) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def save_offset(offset_sec: float, *, source: str = 'position_daemon',
                now: datetime | None = None,
                min_interval_sec: float = MIN_REWRITE_INTERVAL_SEC) -> bool:
    """Persist the daemon's calibration. Returns True if the file was written.

    Refuses implausible values (a corrupt estimate must never poison the
    fallback path) and throttles rewrites of a stable value.
    """
    now = now or datetime.now(timezone.utc)
    try:
        off = float(offset_sec)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(off) or abs(off) > SANITY_SEC:
        return False
    path = paths.broker_clock_state()
    prev = paths.read_json_safe(path, None, label='broker_clock')
    if isinstance(prev, dict):
        try:
            moved = abs(float(prev.get('offset_sec')) - off) > REWRITE_DRIFT_SEC
        except (TypeError, ValueError):
            moved = True
        stamped = _parse_iso(prev.get('measured_at'))
        fresh = stamped is not None and \
            (now - stamped).total_seconds() < min_interval_sec
        if not moved and fresh:
            return False
    paths.write_json_atomic(path, {
        'offset_sec': round(off, 3),
        'measured_at': now.isoformat(),
        'source': source,
    })
    return True


def load_offset(max_age_sec: float = DEFAULT_MAX_AGE_SEC,
                now: datetime | None = None) -> float | None:
    """The last calibration the daemon CONFIRMED, or None = trust nothing.

    None (not 0.0) on missing/corrupt/stale/implausible: 0.0 is a legitimate
    measurement (a UTC broker), and conflating 'unmeasured' with 'zero' is
    exactly the bug class this file exists to kill.
    """
    now = now or datetime.now(timezone.utc)
    data = paths.read_json_safe(paths.broker_clock_state(), None,
                                label='broker_clock')
    if not isinstance(data, dict):
        return None
    try:
        off = float(data.get('offset_sec'))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(off) or abs(off) > SANITY_SEC:
        return None
    stamped = _parse_iso(data.get('measured_at'))
    if stamped is None or (now - stamped).total_seconds() > max_age_sec:
        return None
    return off
