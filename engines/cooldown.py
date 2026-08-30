"""Post-open cooldown — migrated from legacy engine_state.cooldowns.

Legacy behavior (Hermes_Full_Backup engine_state.json): after the engine
starts (or the market opens), block NEW entries for a short window while
spreads are wide and the first ticks are noisy.

XAUUSD opens Sun 23:00 UTC (Tehran 02:30 Mon). Legacy used a post_open
cooldown; we apply it automatically every week after the market open plus
on daemon startup (restart mid-session keeps a shorter guard).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engines import paths  # state paths resolved at CALL time (test-safe)

POST_OPEN_COOLDOWN_MIN = 15      # after weekly market open
RESTART_COOLDOWN_MIN = 5         # after engine restart mid-session


def _load() -> dict:
    state_file = paths.cooldown_state()
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(state: dict):
    state_file = paths.cooldown_state()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=1), encoding="utf-8")


def _market_open_utc(now: datetime) -> datetime:
    """Most recent XAUUSD weekly open (Sun 23:00 UTC) on or before `now`."""
    # weekday(): Mon=0..Sun=6; find most recent Sunday
    days_since_sunday = (now.weekday() - 6) % 7
    sunday = (now - timedelta(days=days_since_sunday)).replace(
        hour=23, minute=0, second=0, microsecond=0
    )
    if sunday > now:  # Sunday today before 23:00 → previous week's open
        sunday -= timedelta(days=7)
    return sunday


def set_cooldown(reason: str, minutes: int, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    state = _load()
    state[reason] = {"until": (now + timedelta(minutes=minutes)).isoformat()}
    _save(state)
    return state


def ensure_startup_cooldown(now: datetime | None = None) -> dict:
    """Called by master on startup: arm the restart guard ONLY on a REAL restart.

    BUG FIX 2026-08-30: master runs as a fresh process from cron every 15
    minutes, so 'once per process' still re-armed a 5-min guard on EVERY
    tick — and each cycle finishes inside its own guard window, so
    restart_cooldown killed 100% of entries (replay: 27/184 candidates).
    Now: if the previous master run was < 30 min ago this is a normal cron
    tick → no guard. A gap ≥ 30 min (crash, reboot, manual stop) → arm 5 min.
    """
    now = now or datetime.now(timezone.utc)
    state = _load()
    last = (state.get('_last_master_run') or {}).get('at')
    real_restart = True
    if last:
        try:
            dt = datetime.fromisoformat(last)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            real_restart = (now - dt) >= timedelta(minutes=30)
        except Exception:
            real_restart = True
    state['_last_master_run'] = {'at': now.isoformat()}
    if real_restart:
        state['restart'] = {'until': (now + timedelta(minutes=RESTART_COOLDOWN_MIN)).isoformat()}
    _save(state)
    return state


def check_entry_cooldown(now: datetime | None = None) -> dict:
    """Gate for new entries. Returns {allowed, reason, until}."""
    now = now or datetime.now(timezone.utc)
    state = _load()

    # weekly post-open cooldown recomputed fresh (no stale state dependency)
    opened = _market_open_utc(now)
    post_open_until = opened + timedelta(minutes=POST_OPEN_COOLDOWN_MIN)
    if now < post_open_until:
        return {
            "allowed": False,
            "reason": "post_open_cooldown",
            "until": post_open_until.isoformat(),
        }

    # restart cooldown (engine just started mid-session)
    until = (state.get("restart") or {}).get("until")
    if until:
        try:
            dt = datetime.fromisoformat(until)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if now < dt:
                return {"allowed": False, "reason": "restart_cooldown", "until": until}
        except Exception:
            pass

    return {"allowed": True, "reason": None, "until": None}


def _is_expired(until: str | None, now: datetime | None = None) -> bool:
    if not until:
        return True
    try:
        dt = datetime.fromisoformat(until)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now or datetime.now(timezone.utc)) >= dt
    except Exception:
        return True
