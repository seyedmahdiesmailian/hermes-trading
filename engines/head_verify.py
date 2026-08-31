"""b50 — verify a COMMITTED HEAD by running the FULL suite inside it.

Why this module exists (proven, not hypothetical): commit 920ed0d shipped
tests/test_b45_double_sell.py + probes but staged WITHOUT the two source
fixes (selective staging — the b42 bug class' new variant). HEAD was
genuinely broken — 3 tests RED — yet scripts/verify_head.sh said OK, because
it only ran test_b42_tracked_imports + test_b44_clean_checkout: import
integrity, not behaviour. Import checks answer "does the commit boot"; only
the suite answers "does the commit work".

The obstacle this module also removes: the full suite COULD NOT run against
a checkout at all. Every test module hardcoded
`sys.path.insert(0, '/home/ai/hermes-trading')`, so discovery imported the
PRODUCTION code instead of the tree under test (unittest then aborts with
"module incorrectly imported from ..."), and the git-based integrity tests
ran `git` in the production repo, certifying the wrong tree. b50 step 1 made
tests/ location-independent (root derived from __file__); this module is the
mechanism that finally runs HEAD through it.

METHOD — `git worktree add --detach <tmp> <sha>`: an exact committed tree
that still carries a `.git` pointer, so the suite's own git checks
(test_b42's HEAD scan, test_b44's archive, test_b46's dirty scan) operate on
THE TREE UNDER TEST, not on production. `git archive` cannot do that — it has
no git dir, which is why those tests ERROR in an archived tree. The worktree
is detached and removed afterwards; production's master checkout is never
moved, so this can never disturb a running system.

Isolation: the child runs with a MINIMAL environment (PATH/HOME only) plus
HERMES_DATA_ROOT=<the worktree>, so (a) no .env token or HERMES_* leaks in,
(b) any state a test forgets to redirect lands in the throwaway tree, never
in the live data/ tree, and (c) the git scans see a clean worktree.

The verdict is STAMPED into data/ops/head_verified.json — the seam b45's
push gate reads: a commit is only "verified" if the FULL suite passed inside
it, not merely because it imports.

Fail-safe by contract (b49 discipline): this module NEVER raises — it returns
a dict, and every swallow calls selfcheck.fail() so a broken verifier is
provable under --self-check instead of silently reporting nothing. Telegram
alerting stays in scripts/verify_head.sh (one writer, one voice).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_STR = str(Path(__file__).resolve().parents[1])
if REPO_STR not in sys.path:
    sys.path.insert(0, REPO_STR)

from engines import paths, selfcheck  # noqa: E402

# The stamp file, relative to the active data root (engines.paths seam).
# Written ONLY for a real verdict on a real sha; b45's git_sync push gate
# reads it (sha must match HEAD, verdict must be OK, age < ~1h).
STAMP_REL = 'ops/head_verified.json'

# Full-suite budget. The suite is ~50s on this box; 600s is generous slack
# so a slow tick degrades to a TIMEOUT verdict, never to a hang.
SUITE_TIMEOUT_SEC = int(os.environ.get('HERMES_VERIFY_TIMEOUT', '600'))

# States: OK | BROKEN | TIMEOUT | ERROR. Four distinct signatures on purpose
# (b49 lesson): a broken verifier must never look like a clean one, and
# "never verified" (no stamp at all) must differ from all four.
VERDICTS = ('OK', 'BROKEN', 'TIMEOUT', 'ERROR')


def _now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def stamp_path() -> Path:
    """Call-time accessor (engines.paths convention, b39)."""
    return paths.data_dir() / STAMP_REL


def write_stamp(sha: str, verdict: str, *, ref: str = 'HEAD',
                tests: int | None = None, seconds: float | None = None,
                note: str = '') -> dict | None:
    """Record the verdict for `sha`. Atomic write; never raises.

    An ERROR verdict IS stamped: b45 must distinguish "verified broken" from
    "never verified", and a dead verifier must not freeze pushes silently.
    """
    payload = {'sha': sha, 'ref': ref, 'verdict': verdict, 'at': _now(),
               'tests': tests,
               'seconds': (round(seconds, 1) if seconds is not None else None),
               'note': (note or '')[:400]}
    try:
        paths.write_json_atomic(stamp_path(), payload, indent=1)
        return payload
    except Exception as exc:
        selfcheck.fail('head_verify stamp write', exc)
        return None


def read_stamp() -> dict | None:
    """The last stamped verdict, or None (never verified / unreadable)."""
    try:
        data = paths.read_json_safe(stamp_path(), default=None,
                                    label='head_verified')
        return data if isinstance(data, dict) else None
    except Exception as exc:
        selfcheck.fail('head_verify stamp read', exc)
        return None


def _git(*args: str, cwd: Path | str | None = None):
    return subprocess.run(['git', *args], cwd=str(cwd or REPO_STR),
                          capture_output=True, text=True, timeout=120)


def resolve_sha(ref: str = 'HEAD') -> str | None:
    """Full sha of `ref` in this repo, or None. Never raises."""
    try:
        r = _git('rev-parse', ref)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception as exc:
        selfcheck.fail('head_verify resolve_sha', exc)
        return None


def _tail(text: str, n: int = 25) -> str:
    lines = [l for l in (text or '').splitlines() if l.strip()]
    return '\n'.join(lines[-n:])


def parse_counts(output: str) -> int | None:
    """The 'Ran N tests' line from unittest's summary, if present.

    Anti-vacuity fuel: a suite that collected 3 tests because discovery died
    must not read as a pass, so the caller compares this against the working
    tree's own count.
    """
    for line in reversed((output or '').splitlines()):
        if line.startswith('Ran '):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return None


def verify_ref(ref: str = 'HEAD', *, timeout: int | None = None) -> dict:
    """Run the FULL suite inside a clean, detached worktree of `ref`.

    Returns {'sha','ref','verdict','tests','seconds','tail','note'}.
    NEVER raises: an internal failure is verdict=ERROR with the reason in
    `note` — loud to the caller, invisible to a trading path.
    """
    budget = timeout or SUITE_TIMEOUT_SEC
    out = {'sha': None, 'ref': ref, 'verdict': 'ERROR', 'tests': None,
           'seconds': None, 'tail': '', 'note': ''}
    t0 = time.time()
    try:
        sha = resolve_sha(ref)
        out['sha'] = sha
        if not sha:
            out['note'] = f'cannot resolve ref {ref!r} in {REPO_STR}'
            return out
        base = Path(tempfile.mkdtemp(prefix='hermes_headverify_'))
        wt = base / 'checkout'
        try:
            shutil.rmtree(wt, ignore_errors=True)
            wt.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            selfcheck.fail('head_verify prepare', exc)
            out['note'] = f'cannot prepare {wt}: {exc}'
            out['seconds'] = round(time.time() - t0, 1)
            shutil.rmtree(base, ignore_errors=True)
            return out
        # A hard kill mid-run can leave stale admin entries behind; prune
        # first so a leftover registration can never block a verification.
        _git('worktree', 'prune')
        add = _git('worktree', 'add', '--detach', str(wt), sha)
        if add.returncode != 0:
            out['note'] = ('git worktree add failed: '
                           + (add.stderr or add.stdout).strip()[:300])
            out['seconds'] = round(time.time() - t0, 1)
            shutil.rmtree(base, ignore_errors=True)
            return out
        try:
            env = {'PATH': '/usr/bin:/bin', 'HOME': str(wt),
                   'HERMES_DATA_ROOT': str(wt),
                   # recursion guard: the inner suite contains
                   # tests/test_b50_*.py, whose expensive end-to-end tests
                   # must NOT fork another verification from inside one
                   # (they are re-enabled by HERMES_B50_VERIFY=1).
                   'HERMES_B50_NESTED': '1'}
            try:
                r = subprocess.run(
                    [sys.executable, '-m', 'unittest', 'discover',
                     '-s', 'tests'],
                    cwd=str(wt), env=env, capture_output=True, text=True,
                    timeout=budget)
                combined = (r.stdout or '') + '\n' + (r.stderr or '')
                out['tests'] = parse_counts(combined)
                out['tail'] = _tail(combined)
                out['verdict'] = 'OK' if r.returncode == 0 else 'BROKEN'
            except subprocess.TimeoutExpired as exc:
                raw = exc.stdout or b''
                text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) \
                    else str(raw)
                out['verdict'] = 'TIMEOUT'
                out['tail'] = _tail(text)
                out['note'] = f'suite exceeded {budget}s on {sha[:7]}'
        except Exception as exc:
            out['verdict'] = 'ERROR'
            out['note'] = f'{type(exc).__name__}: {exc}'[:400]
            selfcheck.fail('head_verify suite run', exc)
        finally:
            rm = _git('worktree', 'remove', '--force', str(wt))
            if rm.returncode != 0:
                shutil.rmtree(wt, ignore_errors=True)
                _git('worktree', 'prune')
            shutil.rmtree(base, ignore_errors=True)
        out['seconds'] = round(time.time() - t0, 1)
        return out
    except Exception as exc:
        out['verdict'] = 'ERROR'
        out['note'] = f'{type(exc).__name__}: {exc}'[:400]
        out['seconds'] = round(time.time() - t0, 1)
        selfcheck.fail('head_verify outer', exc)
        return out


def main(argv=None) -> int:
    """CLI: print the verdict as JSON. Exit 0=OK, 1=BROKEN, 2=TIMEOUT/ERROR.

    Stamps data/ops/head_verified.json ONLY when HERMES_STAMP=1 (the
    verify_head.sh path) — a probe run must never forge a verification stamp.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == '--self-check':
        os.environ['HERMES_SELFCHECK'] = '1'
        argv = argv[1:]
    ref = argv[0] if argv else 'HEAD'
    res = verify_ref(ref)
    if os.environ.get('HERMES_STAMP') == '1' and res['sha']:
        res['stamped'] = bool(write_stamp(
            res['sha'], res['verdict'], ref=ref, tests=res['tests'],
            seconds=res['seconds'], note=res['note']))
    print(json.dumps({k: v for k, v in res.items() if k != 'tail'},
                     ensure_ascii=False))
    return {'OK': 0, 'BROKEN': 1}.get(res['verdict'], 2)


if __name__ == '__main__':
    sys.exit(main())
