"""Pure helpers for the per-run autopilot report (b85).

Why a separate module: ``scripts/autopilot_report.py`` is a *script* — it
sends Telegram and rewrites state at import time, so its logic cannot be
unit-tested. The attribution rule below is exactly the kind of thing that
must be pinned by tests, because getting it wrong produces a report that
LIES about what the system did.

The demonstrated bug (2026-09-05, 13:00 report): a run was cut off by the
55-minute ceiling (rc=124) and had committed nothing. The report compared
``prev_head..HEAD`` and found one commit — a *manual* fix I had made at
11:53, between two runs. It printed

    ⏱️ این اجرا به سقف زمانی خورد و قطع شد، اما کارش کامیت شده بود
    🛠 تغییرات این اجرا:  · autopilot: rc=143 ...
    📌 1 تغییر کد کامیت و روی گیت‌هاب ثبت شد

Every one of those three lines was false. The run did nothing; the work was
mine; and "کارش کامیت شده بود" told the operator that a lost step was safe
when it had never existed.

The fix is attribution by TIME, not by author: a commit belongs to a run
only if it was made after that run started. Manual, harvest, or other-agent
commits land in a separate bucket and are labelled as such.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

# 'run start' markers are written in UTC by scripts/autopilot.sh
RUN_START_RE = re.compile(r'^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)Z '
                          r'=== autopilot run start ===$', re.M)

# a commit line as produced by `git log --format=%ct\x1f%s`
SEP = '\x1f'


def run_start_from_log(text, on_error=None):
    """Epoch seconds of the LAST 'run start' marker, or None if absent.

    ``on_error`` is called with the exception for any line that cannot be
    parsed, so the caller can route it through selfcheck without this module
    depending on it.
    """
    times = RUN_START_RE.findall(text or '')
    if not times:
        return None
    try:
        dt = datetime.strptime(times[-1], '%Y-%m-%dT%H:%M:%S')
    except ValueError as exc:  # pragma: no cover - malformed log line
        if on_error:
            on_error(exc)
        return None
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def classify_commits(raw, started, on_error=None):
    """Split '<epoch>\\x1f<subject>' lines into (this run's, other).

    ``started`` is the run-start epoch (or None). With no start marker we
    cannot attribute anything by time, so every commit is treated as the
    run's own — the pre-b85 behaviour, and the safe reading when the log is
    missing.
    """
    own, other = [], []
    for line in (raw or '').splitlines():
        if not line.strip():
            continue
        ts, _, subj = line.partition(SEP)
        if not subj:  # no separator: not our format, keep it visible
            own.append(line)
            continue
        try:
            made = int(ts)
        except ValueError as exc:  # pragma: no cover - malformed git line
            if on_error:
                on_error(exc)
            own.append(subj)
            continue
        (own if started is None or made >= started else other).append(subj)
    return own, other
