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


def resolve_sha(ref: str = 'HEAD', repo: Path | str | None = None) -> str | None:
    """Full sha of `ref` in `repo` (default: this code's repo), or None.
    Never raises."""
    try:
        r = _git('rev-parse', ref, cwd=repo)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception as exc:
        selfcheck.fail('head_verify resolve_sha', exc)
        return None


def _tail(text: str, n: int = 25) -> str:
    lines = [l for l in (text or '').splitlines() if l.strip()]
    return '\n'.join(lines[-n:])


# ── b91: stale-worktree self-heal ──────────────────────────────────────
# INCIDENT (2026-09-05): the 21:13 run was hard-killed while its OWN suite
# was inside tests/test_b50_*.py's class-level verify_ref. SIGKILL skips
# Python's `finally`, so the detached worktree stayed registered
# (/tmp/hermes_headverify_*/checkout). The very next suite then went RED on
# test_worktree_is_cleaned_up_after_verification — which runs verify_ref
# itself, so the leak was re-measured by the test that was supposed to
# detect it: a self-poisoning loop no one would ever fix by hand.
#
# `git worktree prune` cannot heal this: prune only drops registrations whose
# directory is GONE, and a killed run leaves the directory behind. The entry
# is, to git, a perfectly valid live worktree.
#
# So the verifier sweeps its own leftovers before it works. Safety: only paths
# matching THIS module's own temp prefix, and only ones older than any live
# verification could be (see STALE_WORKTREE_AFTER_SEC) — a concurrently
# running verifier is never disturbed.
WORKTREE_PREFIX = 'hermes_headverify_'
# A live worktree's age is bounded by the OUTER timeout (verify_head.sh uses
# `timeout 900`, the module budget by default 600). Anything older than the
# larger of the two plus slack is by definition an orphan.
STALE_WORKTREE_AFTER_SEC = int(os.environ.get(
    'HERMES_STALE_WORKTREE_AFTER', str(max(SUITE_TIMEOUT_SEC, 900) + 300)))


def list_worktrees(repo: Path | str | None = None) -> list[dict]:
    """Registered worktrees as [{'path','head','detached','prunable'}].
    Never raises: an unreadable listing returns [] (the sweep then does
    nothing, which is the fail-safe direction)."""
    try:
        r = _git('worktree', 'list', '--porcelain', cwd=repo)
        if r.returncode != 0:
            return []
        out, cur = [], {}
        for line in (r.stdout or '').splitlines():
            if not line.strip():
                if cur:
                    out.append(cur)
                    cur = {}
                continue
            if line.startswith('worktree '):
                cur = {'path': line[len('worktree '):], 'head': None,
                       'detached': False, 'prunable': False}
            elif line.startswith('HEAD '):
                cur['head'] = line[5:].strip()
            elif line.strip() == 'detached':
                cur['detached'] = True
            elif line.startswith('prunable'):
                cur['prunable'] = True
        if cur:
            out.append(cur)
        return out
    except Exception as exc:
        selfcheck.fail('head_verify list_worktrees', exc)
        return []


def _age_sec(path: str, now: float) -> int:
    """Seconds since the leftover's directory was last touched (0 when it
    cannot be stat'ed — a missing dir is handled by prune, not by age)."""
    try:
        return int(now - os.stat(path).st_mtime)
    except OSError:
        return 0


def owner_state(base_dir: str) -> str:
    """'alive' | 'dead' | 'unknown' for a temp worktree's creator.

    verify_ref stamps its throwaway dir with owner.pid BEFORE registering the
    worktree, so any worktree created by this code is attributable. A dead
    owner means the verifier was hard-killed (SIGKILL skips the finally block)
    and the registration is an orphan — removable at once, no age wait.
    'unknown' (no pid file: pre-b91 leftover, or hand-made) falls back to the
    conservative age rule.
    """
    try:
        with open(os.path.join(base_dir, 'owner.pid'), encoding='utf-8') as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return 'unknown'
    try:
        os.kill(pid, 0)
        return 'alive'
    except ProcessLookupError:
        return 'dead'
    except PermissionError:
        return 'alive'
    except OSError:
        return 'unknown'


def sweep_stale_worktrees(*, repo: Path | str | None = None, now: float | None = None,
                          min_age_sec: int | None = None) -> dict:
    """Remove THIS verifier's orphaned temp worktrees. Returns a report.

    Never raises. Removes nothing that is not (a) under the temp prefix this
    module creates and (b) older than min_age_sec (default
    STALE_WORKTREE_AFTER_SEC) — so a live verification running elsewhere on
    the same repo is left alone.
    """
    budget = min_age_sec if min_age_sec is not None else STALE_WORKTREE_AFTER_SEC
    stamp_now = now if now is not None else time.time()
    rep = {'removed': [], 'kept_fresh': [], 'pruned': False, 'errors': []}
    try:
        for wt in list_worktrees(repo):
            p = wt.get('path') or ''
            # The prefix only ever appears in paths THIS module created
            # (tempfile.mkdtemp(prefix=WORKTREE_PREFIX)); the main checkout
            # can never match, so it is structurally unremovable here.
            if WORKTREE_PREFIX in p:
                if not os.path.isdir(p):
                    continue                      # prune below handles it
                base = os.path.dirname(p.rstrip('/'))
                state = owner_state(base)
                age = _age_sec(p, stamp_now)
                if state == 'alive':
                    rep['kept_fresh'].append({'path': p, 'age_sec': age,
                                              'owner': 'alive'})
                    continue
                if state == 'unknown' and age < budget:
                    rep['kept_fresh'].append({'path': p, 'age_sec': age,
                                              'owner': 'unknown'})
                    continue
                r = _git('worktree', 'remove', '--force', p, cwd=repo)
                if r.returncode == 0:
                    rep['removed'].append({'path': p, 'age_sec': age,
                                           'owner': state})
                else:
                    shutil.rmtree(p, ignore_errors=True)
                    rep['removed'].append({'path': p, 'age_sec': age,
                                           'owner': state, 'via': 'rmtree'})
                    rep['errors'].append((r.stderr or r.stdout or '').strip()[:200])
        pr = _git('worktree', 'prune', cwd=repo)
        rep['pruned'] = pr.returncode == 0
        return rep
    except Exception as exc:
        selfcheck.fail('head_verify sweep_stale_worktrees', exc)
        rep['errors'].append(f'{type(exc).__name__}: {exc}'[:200])
        return rep


# ── b45: the push gate ─────────────────────────────────────────────────
# A broken HEAD must never reach GitHub (43c5f52 / 920ed0d: commit shipped,
# verification said BROKEN or never ran, cron's git_sync pushed it anyway,
# and any future re-clone inherits the breakage). git_sync.sh asks
# `push-gate` before pushing; the answer is derived ONLY from the stamp
# this module writes. Fail-open on a missing/stale stamp: a DEAD verifier
# must not freeze pushes forever — but a FRESH verdict is law.
PUSH_GATE_MAX_AGE_SEC = int(os.environ.get('HERMES_PUSH_GATE_MAX_AGE', '3600'))


def decide_push(stamp, head_sha: str, *, now=None,
                max_age_sec: int | None = None) -> dict:
    """Pure decision: {'push': bool, 'reason': str}.

    Push ONLY when the full-suite verifier recently certified THIS exact
    commit (verdict OK, sha == HEAD, stamp younger than max_age). Every
    fail-open path says so in `reason` — the log must be able to tell
    "verified good" from "verifier silent, pushed anyway" (b49 posture:
    three states, three signatures).
    """
    budget = max_age_sec if max_age_sec is not None else PUSH_GATE_MAX_AGE_SEC
    if not isinstance(stamp, dict) or not stamp:
        return {'push': True,
                'reason': 'no verification stamp — pushing unverified '
                          '(fail-open: verifier never ran or stamp unreadable)'}
    at_raw = str(stamp.get('at') or '')
    try:
        at = datetime.strptime(at_raw, '%Y-%m-%dT%H:%M:%SZ').replace(
            tzinfo=timezone.utc)
    except ValueError:
        return {'push': True,
                'reason': f'stamp timestamp unreadable ({at_raw!r}) — '
                          f'fail-open'}
    now = now or datetime.now(timezone.utc)
    age = int((now - at).total_seconds())
    verdict = str(stamp.get('verdict') or '?')
    sha = str(stamp.get('sha') or '')
    if age > budget:
        return {'push': True,
                'reason': f'stamp is {age}s old (> {budget}s) — verifier '
                          f'silent, fail-open (last: {sha[:7]} '
                          f'{verdict})'}
    if verdict != 'OK':
        return {'push': False,
                'reason': f'HEAD {sha[:7]} verified {verdict} {age}s ago — '
                          f'not pushing a broken commit'}
    if sha != head_sha:
        return {'push': False,
                'reason': f'HEAD {head_sha[:7]} not yet verified (last OK: '
                          f'{sha[:7]}, {age}s ago) — not pushing'}
    return {'push': True,
            'reason': f'HEAD {sha[:7]} verified OK {age}s ago'}


def push_decision(repo: Path | str | None = None) -> dict:
    """Glue: read the live stamp + HEAD of `repo` (default: the CALLER's
    cwd — git_sync cd's into the repo it is about to push, so the gate must
    answer about THAT tree, not wherever the code happens to live).
    Never raises."""
    try:
        head = resolve_sha('HEAD', repo or Path.cwd())
        if not head:
            return {'push': True,
                    'reason': 'cannot resolve HEAD — fail-open'}
        return decide_push(read_stamp(), head)
    except Exception as exc:
        selfcheck.fail('head_verify push_decision', exc)
        return {'push': True, 'reason': f'gate error — fail-open: {exc!r}'}


# ── b51: start-of-run heal ─────────────────────────────────────────────
# The autopilot procedure verifies HEAD as step 4b AFTER the commit. If a
# run dies between step 4 and 4b (or an operator commits by hand), the
# fresh HEAD carries no stamp — and git_sync's deliberate fail-open pushes
# it unverified once the old stamp ages out (~1h). decide_start_verify is
# the pure rule autopilot.sh asks at run START: when it says yes, the run
# re-verifies HEAD immediately, so a crashed run heals its own verification
# on the next tick and the push gate closes again.

def unpushed_count(repo: Path | str | None = None) -> int | None:
    """Commits on HEAD not present in origin/master, or None when the
    comparison is impossible (no origin ref, offline fetch state, not a
    repo). None is NOT zero: callers must not read 'unknown' as 'pushed'."""
    try:
        r = _git('rev-list', '--count', 'origin/master..HEAD',
                 cwd=repo or Path.cwd())
        out = (r.stdout or '').strip()
        return int(out) if r.returncode == 0 and out.isdigit() else None
    except Exception as exc:
        selfcheck.fail('head_verify unpushed_count', exc)
        return None


def decide_start_verify(stamp, head_sha: str | None,
                        ahead: int | None) -> dict:
    """Pure rule (b51): {'needed': bool, 'reason': str}.

    Verify at run start when EITHER half of "the last verdict may not
    describe what cron would push" holds:
      * unpushed commits exist (ahead > 0) — re-verifying also RE-STAMPS
        freshness, so the push gate never fail-opens on a stale stamp for
        a commit that was in fact verified; or
      * the stamp names a different sha than HEAD (crashed run between
        commit and step 4b, or a hand commit) — this exact HEAD has NEVER
        been verified.
    ONE exclusion (alert hygiene, b37 dedupe lesson): HEAD already carries
    a non-OK verdict (BROKEN/TIMEOUT/ERROR). Re-running would page ops
    EVERY HOUR for the same known-broken commit. The fix for a BROKEN HEAD
    is a new commit, which flips the sha-mismatch clause and re-arms
    verification. ahead=None (origin unknown) degrades to the stamp clause
    only.
    """
    if not head_sha:
        return {'needed': False,
                'reason': 'cannot resolve HEAD — skip (fail-safe)'}
    sha = str(stamp.get('sha') or '') if isinstance(stamp, dict) else ''
    verdict = str(stamp.get('verdict') or '?') if isinstance(stamp,
                                                            dict) else '?'
    if sha == head_sha and verdict in ('BROKEN', 'TIMEOUT', 'ERROR'):
        return {'needed': False,
                'reason': f'HEAD {sha[:7]} already carries {verdict} — '
                          f're-verifying hourly would re-page the same '
                          f'broken commit (fix = new commit)'}
    if ahead:  # None and 0 are both falsy — see docstring
        return {'needed': True,
                'reason': f'{ahead} commit(s) ahead of origin — HEAD '
                          f'{head_sha[:7]} may sit unverified when the '
                          f'stamp ages out (last: {sha[:7] or "none"} '
                          f'{verdict})'}
    if sha != head_sha:
        return {'needed': True,
                'reason': f'stamp names {sha[:7] or "nothing"} '
                          f'({verdict}), HEAD is {head_sha[:7]} — fresh '
                          f'HEAD never verified'}
    return {'needed': False,
            'reason': f'HEAD {head_sha[:7]} already verified ({verdict}) '
                      f'and nothing is unpushed'}


def start_verify_decision(repo: Path | str | None = None) -> dict:
    """Glue for the CLI: resolve HEAD + ahead from the CALLER's cwd (b45
    lesson — the gate must answer about the tree that cron pushes, not
    wherever this code lives). Never raises."""
    try:
        head = resolve_sha('HEAD', repo or Path.cwd())
        return decide_start_verify(read_stamp(), head,
                                   unpushed_count(repo or Path.cwd()))
    except Exception as exc:
        selfcheck.fail('head_verify start_verify_decision', exc)
        return {'needed': False,
                'reason': f'decision error — skip (fail-safe): {exc!r}'}



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
        base = Path(tempfile.mkdtemp(prefix=WORKTREE_PREFIX))
        wt = base / 'checkout'
        # b91: stamp the creator's pid BEFORE registering the worktree, so a
        # later sweep can tell "orphan of a killed run" (pid gone) from "a
        # verification running right now" (pid alive) and never disturb the
        # latter. Written first: a worktree that exists was stamped first.
        try:
            (base / 'owner.pid').write_text(str(os.getpid()), encoding='utf-8')
        except Exception as exc:
            selfcheck.fail('head_verify owner stamp', exc)
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
        # b91: prune alone is NOT enough — a killed run leaves the worktree
        # DIRECTORY in place, so git sees a valid live worktree and prune
        # refuses it. Sweep this module's own orphans (prefix + age guarded)
        # first; the report rides on the result so a leak is visible in the
        # verdict instead of only in a red test three runs later.
        out['sweep'] = sweep_stale_worktrees()
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

    b45 mode `push-gate`: print the git_sync decision as JSON on stdout
    ('{push, reason}'), exit 0 = push allowed, 1 = blocked. Reads the stamp
    only; never verifies, never writes, never raises.

    b51 mode `start-verify`: print {needed, reason} (exit 0 = verify now,
    1 = skip) — autopilot.sh asks this at run START so a crashed run heals
    its own missing verification on the next tick, before the push gate's
    fail-open window can ship an unverified HEAD.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == '--self-check':
        os.environ['HERMES_SELFCHECK'] = '1'
        argv = argv[1:]
    if argv and argv[0] in ('push-gate', 'start-verify'):
        # stdout is the CONTRACT (one JSON line for the caller); readers like
        # paths.read_json_safe print WARN lines — route them to stderr so a
        # corrupt stamp degrades visibly without poisoning the parse.
        real_out, sys.stdout = sys.stdout, sys.stderr
        try:
            if argv[0] == 'push-gate':
                dec = push_decision()
                key, allow = 'push', 0
            else:
                dec = start_verify_decision()
                key, allow = 'needed', 0
        finally:
            sys.stdout = real_out
        print(json.dumps(dec, ensure_ascii=False))
        return allow if dec[key] else 1
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
