"""b46 — the ONE canonical detector of ABANDONED UNCOMMITTED code.

Why this module exists (proven, not hypothetical): b36 was found FULLY
IMPLEMENTED — 403 lines (fixtures + drift test + 4 consumer migrations) —
but left staged-and-dirty in the working tree by an interrupted autopilot
run. Every safety net sees only HEAD: cron runs committed code, git_sync
pushes committed code, verify_head.sh verifies committed code. A finished
deliverable sitting uncommitted is invisible to all three, the backlog
still says `todo`, and one `git checkout -- .` / reset / crash erases a
whole run's work with no trace.

RULE (read-only, display-only): `git status --porcelain -z` filtered to
SOURCE files (*.py / *.sh — the b42/b44 lesson is that .sh matters just as
much: verify_head.sh itself was once the untracked file) under the code
dirs (tests/, engines/, scripts/, notifier/) or at repo root. A source
file whose mtime is older than DIRTY_ALERT_MINUTES while still uncommitted
is no longer "work in progress" — it is abandoned work. Surface it as one
warning line on the ops dashboards and the daily digest.

Deliberately NOT done: never auto-commits, never touches trading state,
never raises. If git is missing, the dir is not a repo (a hermetic test
run under HERMES_DATA_ROOT), or the call fails, scan() returns None and
the panels show nothing — a display reader must never break a panel
(same fail-safe posture as engines.guard_status in b40).

Root resolution: engines.paths.get_data_root() — in production that IS the
repo (/home/ai/hermes-trading); under tests (hermetic / $HERMES_DATA_ROOT)
it is a temp dir that is not a git repo, so the check self-disables and can
never make a test depend on the live tree's dirtiness.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from engines import paths, selfcheck

# A code file untouched this long while still uncommitted = abandoned work,
# not an agent mid-edit. 60 min comfortably exceeds any single edit burst
# but is far under the 3h autopilot cadence, so a crashed run is surfaced
# before the next one starts.
DIRTY_ALERT_MINUTES = 60

# Source extensions whose absence from git breaks a fresh checkout or
# silently loses a run's work (.py is the b42 class; .sh was added by b44).
CODE_SUFFIXES = ('.py', '.sh')

# Directories holding production/test code. Root-level *.py/*.sh
# (hermes_master.py, position_daemon.py, cli.py ...) count too.
CODE_DIRS = ('tests/', 'engines/', 'scripts/', 'notifier/')


def is_code_path(rel: str) -> bool:
    """Repo-relative path is source code we care about being committed."""
    if not rel.endswith(CODE_SUFFIXES):
        return False
    return '/' not in rel or rel.startswith(CODE_DIRS)


def _porcelain_entries(root: Path) -> list[tuple[str, str]] | None:
    """[(status, path)] from `git status --porcelain=v1 -z`, or None on any
    failure (not a repo, git missing, timeout). -z keeps filenames verbatim
    (no octal quoting); for R/C entries the source path is the NEXT field
    and is consumed here so it never leaks as a bogus status line."""
    try:
        r = subprocess.run(
            ['git', 'status', '--porcelain=v1', '-z', '--untracked-files=all'],
            cwd=root, capture_output=True, timeout=15)
    except Exception as e:
        # b49: silent None is correct for panels, but --self-check re-raises
        # so a broken detector can't masquerade as a clean tree.
        selfcheck.fail('dirty_work git call', e)
        return None
    if r.returncode != 0:
        return None
    fields = [f for f in r.stdout.decode('utf-8', 'replace').split('\0') if f]
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(fields):
        line = fields[i]
        i += 1
        if len(line) < 4 or line[2] != ' ':
            continue  # cannot be a status line (defensive)
        status, path = line[:2], line[3:]
        if status[0] in ('R', 'C'):
            i += 1  # rename/copy source path is its own field
        out.append((status, path))
    return out


def scan(root: str | Path | None = None, *, now: datetime | None = None,
         alert_minutes: int = DIRTY_ALERT_MINUTES) -> dict | None:
    """{'files':[{path,status,age_min}], 'count', 'max_age_min'} or None.

    None means "nothing to report": no dirty code, no repo, or git failed.
    A deleted tracked file has no measurable mtime → age_min=None → always
    counts as abandoned (the change itself is the thing at risk).
    """
    root = Path(root) if root else paths.get_data_root()
    entries = _porcelain_entries(root)
    if not entries:
        return None
    now = now or datetime.now(timezone.utc)
    files = []
    for status, rel in entries:
        if not is_code_path(rel):
            continue
        age_min: float | None
        try:
            mtime = (root / rel).stat().st_mtime
            age_min = (now - datetime.fromtimestamp(mtime, tz=timezone.utc)
                       ).total_seconds() / 60.0
        except OSError:
            age_min = None  # deleted / vanished
        if age_min is None or age_min >= alert_minutes:
            files.append({'path': rel, 'status': status, 'age_min': age_min})
    if not files:
        return None
    files.sort(key=lambda f: -(f['age_min'] if f['age_min'] is not None
                                else float('inf')))
    ages = [f['age_min'] for f in files if f['age_min'] is not None]
    return {'files': files, 'count': len(files),
            'max_age_min': max(ages) if ages else None}


def _age_fa(age_min: float | None) -> str:
    if age_min is None:
        return 'سن نامعلوم'
    if age_min < 60:
        return f'{age_min:.0f} دقیقه'
    return f'{age_min / 60:.1f} ساعت'


def describe(res: dict | None, *, short: bool = False) -> str:
    """One Persian display line (empty string for None). Technical tokens
    (commit, working tree, file paths) stay English per dashboard
    convention; prose is Persian."""
    if not res:
        return ''
    files = res['files']
    names = '، '.join(f['path'] for f in files[:3])
    if len(files) > 3:
        names += f" (+{len(files) - 3} دیگر)"
    age = _age_fa(res.get('max_age_min'))
    if short:
        return f"کد commit‌نشده در working tree: {res['count']} فایل، بی‌تغییر از {age}"
    return (f"کد commit‌نشده رهاشده در working tree — {names}"
            f" — بدون تغییر از {age}. ممکن است کار یک اجرای نیمه‌تمام باشد"
            " که هنوز commit نشده و هیچ push ازش محافظت نمی‌کند.")
