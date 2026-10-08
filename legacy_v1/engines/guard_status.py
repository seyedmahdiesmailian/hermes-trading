"""b40: the ONE canonical reader of the guard-degradation alert state.

Why this module exists: hermes_master.alert_degraded_guards() (b37) WRITES
data/ops/guard_alert_state.json whenever the fallback management path loses
its news_lock/time_exit guards — but until b40 NOTHING read it. A degraded
management path was visible only in the ops chat; an operator opening the
dashboards saw green. The lesson from b34/b37/b41 is the same every time:
two modules holding one fact, with no shared seam, drift silently. So the
file shape (state/detail/step/at) is parsed HERE and only here; dashboards,
the daily digest and any future consumer call read()/describe().

Read-only by design: the writer stays hermes_master (it owns the dedupe and
the page), this module only interprets what was written.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from engines import paths

# Contract with hermes_master.alert_degraded_guards() — pinned by
# tests/test_b40_guard_observability.py (writer path == reader path).
ALERT_FILE = "ops/guard_alert_state.json"

# hermes_master re-pages an UNCHANGED degradation at most once per this
# window and rewrites 'at' every time it pages. Kept here (not in
# hermes_master) so the staleness math below and the writer's throttle can
# never disagree; hermes_master imports it back.
GUARD_ALERT_COOLDOWN_SEC = 6 * 3600

# If 'at' is older than cooldown + 4 master cycles (15min each), the writer
# has NOT re-paged recently. That means one of two things: the master itself
# stopped (visible elsewhere on the dashboards), or the condition healed
# while the watchdog was managing — an absent guards key deliberately
# never clears the file (pinned by test_b37), so a recovered degradation can
# linger as a stale record. Either way the display must say "last observed",
# never claim the guards are broken right now.
STALE_AFTER_SEC = GUARD_ALERT_COOLDOWN_SEC + 4 * 900

# Known degraded states (payload['guards']['state'] in hermes_runtime).
STATE_FA = {
    "error": "خطای محاسبهٔ گارد",
    "calendar_unavailable": "تقویم اخبار دیده نشد",
}


def state_path() -> Path:
    """Call-time accessor (engines.paths convention, b39)."""
    return paths.data_dir() / ALERT_FILE


def read(now: datetime | None = None) -> dict | None:
    """Normalized degradation record, or None = nothing observed.

    Fail-safe on purpose: the ALERTING side (hermes_master) is fail-LOUD,
    but a display reader must never crash a dashboard panel or a digest.
    Missing/corrupt/foreign-shaped file → None (read_json_safe quarantines
    corrupt files for forensics).
    """
    data = paths.read_json_safe(state_path(), None, label="guard_alert")
    if not isinstance(data, dict):
        return None
    state = str(data.get("state") or "")
    if not state:
        return None
    # An UNLISTED state still surfaces (fail-loud bias): a future runtime
    # that adds a third degraded state must not become invisible because
    # this dict was never updated.
    at_raw = str(data.get("at") or "")
    age: float | None = None
    try:
        t = datetime.fromisoformat(at_raw.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        age = ((now or datetime.now(timezone.utc)) - t).total_seconds()
    except ValueError:
        pass
    return {
        "state": state,
        "detail": str(data.get("detail") or "")[:200],
        "step": str(data.get("step") or ""),
        "at": at_raw,
        "age_sec": age,
        "stale": bool(age is not None and age > STALE_AFTER_SEC),
    }


def _ago_fa(age_sec: float | None) -> str:
    if age_sec is None:
        return "تاریخ نامعلوم"
    if age_sec < 0:
        age_sec = 0.0
    m = age_sec / 60
    if m < 60:
        return f"{m:.0f} دقیقه پیش"
    h = m / 60
    if h < 48:
        return f"{h:.1f} ساعت پیش"
    return f"{h / 24:.1f} روز پیش"


def describe(rec: dict | None, *, short: bool = False) -> str:
    """One Persian display line for a record (empty string for None).

    short=True is the verdict/home form (single compact clause); the full
    form carries step + detail for the dedicated panels. Technical tokens
    (state, step) stay English per dashboard convention; prose is Persian.
    """
    if not rec:
        return ""
    label = STATE_FA.get(rec["state"], rec["state"])
    ago = _ago_fa(rec["age_sec"])
    if short:
        line = f"گاردهای مدیریت ضعیف شده [{rec['state']}] · آخرین مشاهده {ago}"
    else:
        line = (f"گاردهای ایمنی مدیریت ضعیف شده — {label}"
                f" · step={rec['step'] or '?'} · آخرین مشاهده {ago}")
    if rec.get("stale"):
        line += " (ممکن است برطرف شده باشد — چک نشده)"
    if not short and rec.get("detail"):
        line += f" | {rec['detail'][:120]}"
    return line
