#!/usr/bin/env python3
"""b47 — HARVEST abandoned uncommitted work before the next autopilot run.

Why: b36 was found FULLY IMPLEMENTED (403 lines) but left staged-and-dirty
in the working tree by an interrupted run; b46 built the detector
(engines/dirty_work) so the dashboards SEE such leftovers, but the next
autopilot run still started blind — the agent read the backlog, picked the
top todo, and had no idea a previous run's finished deliverable was sitting
in the tree (the b36 recovery was luck-of-the-audit, not procedure).

This script turns it into procedure. It is a PRINT-ONLY helper: it never
commits, never edits, never touches trading paths. scripts/autopilot.sh
calls it before building the PROMPT; when scan() fires, the emitted block
is prepended so the agent's FIRST job is to verify + commit the leftover
as its own commit, and only then pick the top todo.

Fail-safe posture (same as b40/b46 readers): any error — git missing,
non-repo, timeout, import failure — prints nothing and exits 0. A broken
harvest check must never block the autopilot run itself.

Test seam: HERMES_REPO_ROOT points the scan at a throwaway repo (same
seam b46 introduced for autopilot_digest.py), so tests never depend on
whether the live tree happens to be mid-edit.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Code root: dirty_work is imported from the REAL repo (same posture as
# autopilot_digest.py's ROOT — code location, not state). HERMES_REPO_ROOT
# only redirects the SCAN ROOT (the repo whose git status we read), so a
# test can point the detector at a throwaway repo without breaking imports.
CODE_ROOT = Path('/home/ai/hermes-trading')
SCAN_ROOT = Path(os.getenv('HERMES_REPO_ROOT', str(CODE_ROOT)))
sys.path.insert(0, str(CODE_ROOT))


def harvest_block(res: dict | None) -> str:
    """The instruction block prepended to the autopilot prompt when a
    previous run's code is still uncommitted. Empty string when clean."""
    if not res:
        return ''
    files = res['files']
    names = '\n'.join(f"  - {f['path']} (git status '{f['status']}')"
                      for f in files)
    age = res.get('max_age_min')
    age_txt = (f'{age / 60:.1f} hours' if age is not None and age >= 60
               else (f'{age:.0f} minutes' if age is not None
                     else 'unknown age'))
    return (
        'STEP 0 (b47 HARVEST — do this BEFORE picking a backlog item):\n'
        f'UNCOMMITTED CODE detected from a previous run ({res["count"]} file(s),'
        f' untouched for {age_txt} — b46 detector says abandoned, not mid-edit):\n'
        f'{names}\n'
        'Verify it first: run `python3 -m unittest discover -s tests`.\n'
        'If green, commit it as its OWN commit (`git add -A && git commit -m '
        '"harvest: <what it is>"`, then `bash scripts/verify_head.sh`) BEFORE '
        'starting the task below. If the tests are red or the code is '
        'half-finished, fix or revert it, then say what you did in your final '
        'report. Only after the tree holds no abandoned code, pick the TOP '
        'todo item and follow the normal procedure. Never leave harvested '
        'work uncommitted again — cron, git_sync and verify_head all see '
        'only HEAD.'
    )


def main() -> int:
    try:
        from engines import dirty_work
        res = dirty_work.scan(SCAN_ROOT)
        block = harvest_block(res)
        if block:
            print(block)
    except Exception:
        pass  # a broken harvest check must never block the run
    return 0


if __name__ == '__main__':
    sys.exit(main())
