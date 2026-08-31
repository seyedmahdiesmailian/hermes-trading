"""b45 — git_sync must never push an UNVERIFIED HEAD.

Why: scripts/git_sync.sh runs on cron every 15 min and pushed whatever HEAD
was. Real history: 43c5f52 (new module left untracked) and 920ed0d (tests
staged WITHOUT their source fixes — 3 tests RED on a clean checkout) both
reached GitHub that way, so a re-clone/restore-from-remote would inherit a
tree that cannot run. b50 gave verify_head.sh a full-suite verdict stamped
into data/ops/head_verified.json; this item wires THAT stamp into the push
path: engines/head_verify.py `push-gate` answers from the stamp alone, and
git_sync.sh asks before every push.

The posture is deliberately asymmetric (and each branch is pinned):
  * FRESH verdict is law — BROKEN blocks, OK-for-another-sha blocks.
  * MISSING or STALE (>1h) stamp FAILS OPEN — a dead verifier must not
    freeze pushes forever (the repo is the only backup of this system).
  * Every outcome logs its REASON, so "verified good", "blocked" and
    "pushed unverified (fail-open)" are three different lines (b49).

Tests here are behavioural where cheap (decide_push is pure; the CLI runs
as a subprocess against a throwaway data root) and static where the subject
is bash (the script must call the gate, must log the block, must not
re-page Telegram — verify_head.sh is the one voice, b40 convention).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'tests'))

import hermetic  # noqa: E402
from engines import head_verify  # noqa: E402

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
HEAD_SHA = 'a' * 40
OTHER_SHA = 'b' * 40


def _stamp(verdict='OK', sha=HEAD_SHA, age_sec=60):
    at = (NOW - timedelta(seconds=age_sec)).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {'sha': sha, 'verdict': verdict, 'at': at}


class DecidePush(unittest.TestCase):
    """The pure rule — every branch has its own signature."""

    def test_fresh_ok_stamp_for_head_pushes(self):
        d = head_verify.decide_push(_stamp(), HEAD_SHA, now=NOW)
        self.assertTrue(d['push'])
        self.assertIn('verified OK', d['reason'])

    def test_fresh_broken_stamp_blocks(self):
        # The 920ed0d shape: HEAD imports fine but the suite is RED inside
        # it. The old import-only verifier would have stamped OK; b50 says
        # BROKEN; the gate must refuse the push.
        d = head_verify.decide_push(_stamp(verdict='BROKEN'), HEAD_SHA,
                                    now=NOW)
        self.assertFalse(d['push'])
        self.assertIn('broken', d['reason'].lower())

    def test_timeout_verdict_blocks_too(self):
        d = head_verify.decide_push(_stamp(verdict='TIMEOUT'), HEAD_SHA,
                                    now=NOW)
        self.assertFalse(d['push'])

    def test_ok_for_a_different_sha_blocks(self):
        # The 43c5f52 shape: a NEW commit landed after the last
        # verification — it has never been checked, push must wait.
        d = head_verify.decide_push(_stamp(sha=OTHER_SHA), HEAD_SHA,
                                    now=NOW)
        self.assertFalse(d['push'])
        self.assertIn('not yet verified', d['reason'])

    def test_missing_stamp_fails_open(self):
        for empty in (None, {}, 'garbage'):
            d = head_verify.decide_push(empty, HEAD_SHA, now=NOW)
            self.assertTrue(d['push'], f'{empty!r} must fail OPEN')
            self.assertIn('fail-open', d['reason'])

    def test_stale_stamp_fails_open(self):
        # A dead verifier may not freeze backups forever: older than the
        # budget, even a BROKEN stamp stops holding the gate.
        d = head_verify.decide_push(_stamp(verdict='BROKEN', age_sec=7200),
                                    HEAD_SHA, now=NOW)
        self.assertTrue(d['push'])
        self.assertIn('fail-open', d['reason'])

    def test_unreadable_timestamp_fails_open(self):
        d = head_verify.decide_push({'sha': HEAD_SHA, 'verdict': 'OK',
                                     'at': 'not-a-date'},
                                    HEAD_SHA, now=NOW)
        self.assertTrue(d['push'])
        self.assertIn('fail-open', d['reason'])

    def test_future_stamp_is_treated_as_fresh(self):
        # Clock skew must not turn a good stamp into a permanent block.
        d = head_verify.decide_push(_stamp(age_sec=-120), HEAD_SHA, now=NOW)
        self.assertTrue(d['push'])

    def test_blocked_reason_names_the_commit(self):
        # The log line must be actionable: which sha, which verdict.
        d = head_verify.decide_push(_stamp(verdict='BROKEN'), HEAD_SHA,
                                    now=NOW)
        self.assertIn(HEAD_SHA[:7], d['reason'])


class PushDecisionGlue(unittest.TestCase):
    """The glue reads the stamp from the ACTIVE data root (b39 seam) —
    tests use hermetic so the live tree's stamp is never consulted."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = hermetic.use_temp_data_root()

    @classmethod
    def tearDownClass(cls):
        hermetic.release()

    def test_no_stamp_yet_fails_open(self):
        # alphabetical order inside the class means another test may have
        # stamped first — start from a genuinely unstamped root.
        if head_verify.stamp_path().exists():
            head_verify.stamp_path().unlink()
        self.assertIsNone(head_verify.read_stamp())
        d = head_verify.push_decision()
        self.assertTrue(d['push'])
        self.assertIn('fail-open', d['reason'])

    def test_ok_stamp_matching_real_head_pushes(self):
        head = head_verify.resolve_sha('HEAD')
        self.assertIsNotNone(head)
        head_verify.write_stamp(head, 'OK', ref='HEAD', tests=369,
                                seconds=50.0)
        d = head_verify.push_decision()
        self.assertTrue(d['push'], d['reason'])

    def test_broken_stamp_for_real_head_blocks(self):
        head = head_verify.resolve_sha('HEAD')
        head_verify.write_stamp(head, 'BROKEN', ref='HEAD', tests=3,
                                seconds=50.0, note='3 RED')
        d = head_verify.push_decision()
        self.assertFalse(d['push'], 'the gate let a BROKEN HEAD through')

    def test_stamp_for_an_older_commit_blocks_new_head(self):
        head_verify.write_stamp('deadbeef' * 5, 'OK', ref='HEAD',
                                tests=369, seconds=50.0)
        d = head_verify.push_decision()
        self.assertFalse(d['push'])
        self.assertIn('not yet verified', d['reason'])


class GateCli(unittest.TestCase):
    """git_sync talks to the gate through the CLI; pin the contract
    (stdout JSON {push, reason}, exit 0=push / 1=block) for real."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = hermetic.use_temp_data_root()

    @classmethod
    def tearDownClass(cls):
        hermetic.release()

    def _run(self):
        env = dict(os.environ)
        env['HERMES_DATA_ROOT'] = str(self.tmp)
        return subprocess.run(
            [sys.executable, str(REPO / 'engines' / 'head_verify.py'),
             'push-gate'],
            capture_output=True, text=True, timeout=60, env=env,
            cwd=str(REPO))

    def test_cli_allow_and_block_exit_codes(self):
        head = head_verify.resolve_sha('HEAD')
        head_verify.write_stamp(head, 'OK', tests=369, seconds=50.0)
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        payload = json.loads(r.stdout)
        self.assertTrue(payload['push'])

        head_verify.write_stamp(head, 'BROKEN', tests=3, seconds=50.0)
        r = self._run()
        self.assertEqual(r.returncode, 1, 'a BROKEN HEAD must exit 1')
        payload = json.loads(r.stdout)
        self.assertFalse(payload['push'])

    def test_cli_never_raises_even_on_garbage_stamp(self):
        p = head_verify.stamp_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{not json', encoding='utf-8')
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertTrue(json.loads(r.stdout)['push'],
                        'unreadable stamp must fail OPEN, not crash')


class GitSyncScriptIsWired(unittest.TestCase):
    """Static half: the bash must actually consult the gate, log every
    outcome distinctly, and stay silent when there is nothing to push."""

    SRC = (REPO / 'scripts' / 'git_sync.sh').read_text(encoding='utf-8')

    def test_script_calls_the_gate(self):
        self.assertIn('push-gate', self.SRC)
        self.assertIn('engines/head_verify.py', self.SRC)

    def test_block_is_logged_and_push_does_not_happen(self):
        lines = [l.strip() for l in self.SRC.splitlines()]
        i = next(k for k, l in enumerate(lines) if 'PUSH BLOCKED' in l)
        # the block branch must exit before the push command (the push is a
        # multi-line continuation: match the 'push origin' line itself)
        push_at = next(k for k, l in enumerate(lines)
                       if 'push origin master' in l)
        self.assertLess(i, push_at,
                        'the blocked branch falls through to the push')
        self.assertIn('exit 0', ' '.join(lines[i:i + 3]),
                      'blocked branch must exit (cron noise = alert rot)')

    def test_gate_rc_captured_immediately_after_assignment(self):
        # b44 lesson: `RC=$?` must sit directly after the command whose
        # status it claims — never after an `fi` or another command.
        lines = [l.strip() for l in self.SRC.splitlines() if l.strip()]
        for k, l in enumerate(lines):
            if l == 'GATE_RC=$?':
                self.assertIn('head_verify.py', lines[k - 1],
                              'GATE_RC=$? no longer follows the gate call')

    def test_idle_tick_stays_silent(self):
        # ahead=0 must exit BEFORE the gate runs, or every 15-min idle cron
        # tick logs a gate line and the log becomes unreadable. Match the
        # gate CALL line, not the docstring that mentions push-gate.
        lines = [l.strip() for l in self.SRC.splitlines()]
        ahead = next(k for k, l in enumerate(lines) if 'AHEAD=' in l)
        gate = next(k for k, l in enumerate(lines)
                    if l.startswith('GATE=$(timeout'))
        self.assertLess(ahead, gate)

    def test_git_sync_does_not_page_telegram(self):
        # One writer, one voice (b40): verify_head.sh already pages on a
        # BROKEN verdict; a 15-min re-page from git_sync would be pure
        # noise. The gate must stay log-only.
        self.assertNotIn('send_ops', self.SRC)
        self.assertNotIn('notifier.telegram', self.SRC)

    def test_fail_open_branch_exists(self):
        # A dead verifier must not freeze pushes: the non-0/1 rc branch
        # must push anyway AND say fail-open in the log.
        self.assertIn('fail-open', self.SRC)


class GitSyncGateEndToEnd(unittest.TestCase):
    """The b45 deliverable replayed for real (b47/b49 discipline): a
    sed-moved copy of git_sync.sh runs against a THROWAWAY repo with a
    local bare origin — BROKEN stamp must leave the commit unpushed, OK
    stamp must push it. Never touches the real remote."""

    def _mk_repo(self, tmp):
        root = Path(tmp) / 'repo'
        remote = Path(tmp) / 'origin.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)],
                       check=True)
        root.mkdir(parents=True)
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t',
                   GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')
        def g(*a):
            return subprocess.run(['git', *a], cwd=str(root), env=env,
                                  check=True, capture_output=True)
        g('init', '-q', '-b', 'master')
        (root / 'a.txt').write_text('1')
        (root / '.git_token').write_text('')  # empty: cat succeeds, creds unused
        g('add', '-A')
        g('commit', '-qm', 'base')
        g('remote', 'add', 'origin', str(remote))
        g('push', '-q', 'origin', 'master')
        (root / 'a.txt').write_text('2')
        g('commit', '-qam', 'unverified head')
        return root, env

    def _run_sync(self, root, data_root):
        src = (REPO / 'scripts' / 'git_sync.sh').read_text(encoding='utf-8')
        src = src.replace('cd /home/ai/hermes-trading || exit 1',
                          f'cd {root} || exit 1')
        src = src.replace('python3 engines/head_verify.py',
                          f'python3 {REPO / "engines" / "head_verify.py"}')
        src = src.replace('logs/git_sync.log', str(root / 'sync.log'))
        script = root / 'sync.sh'
        script.write_text(src)
        env = dict(os.environ, HERMES_DATA_ROOT=str(data_root))
        r = subprocess.run(['bash', str(script)], capture_output=True,
                           text=True, timeout=120, env=env)
        log = (root / 'sync.log')
        return r.returncode, (log.read_text() if log.exists() else '')

    def _stamp(self, root, data_root, verdict):
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(root),
                             capture_output=True, text=True).stdout.strip()
        at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        ops = data_root / 'data' / 'ops'
        ops.mkdir(parents=True, exist_ok=True)
        (ops / 'head_verified.json').write_text(json.dumps(
            {'sha': sha, 'verdict': verdict, 'at': at}), encoding='utf-8')
        return sha

    def _ahead(self, root):
        out = subprocess.run(['git', 'rev-list', '--count',
                              'origin/master..HEAD'], cwd=str(root),
                             capture_output=True, text=True).stdout.strip()
        return int(out)

    def test_broken_stamp_blocks_and_ok_stamp_pushes(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='hermes_b45_') as tmp:
            root, _ = self._mk_repo(tmp)
            data_root = Path(tmp) / 'state'
            self.assertEqual(self._ahead(root), 1)

            self._stamp(root, data_root, 'BROKEN')
            rc, log = self._run_sync(root, data_root)
            self.assertEqual(rc, 0, log)
            self.assertIn('PUSH BLOCKED', log)
            self.assertEqual(self._ahead(root), 1,
                             'gate said BLOCKED but the commit reached origin')

            self._stamp(root, data_root, 'OK')
            rc, log = self._run_sync(root, data_root)
            self.assertEqual(rc, 0, log)
            self.assertEqual(self._ahead(root), 0,
                             'verified-OK HEAD was not pushed: ' + log)
            self.assertIn('push rc=0', log)

    def test_stale_stamp_fails_open_and_pushes(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='hermes_b45_') as tmp:
            root, _ = self._mk_repo(tmp)
            data_root = Path(tmp) / 'state'
            sha = self._stamp(root, data_root, 'BROKEN')
            # age it past the budget: a dead verifier must not freeze pushes
            ops = data_root / 'data' / 'ops' / 'head_verified.json'
            old = (datetime.now(timezone.utc)
                   - timedelta(seconds=head_verify.PUSH_GATE_MAX_AGE_SEC + 600)
                   ).strftime('%Y-%m-%dT%H:%M:%SZ')
            ops.write_text(json.dumps({'sha': sha, 'verdict': 'BROKEN',
                                       'at': old}), encoding='utf-8')
            rc, log = self._run_sync(root, data_root)
            self.assertEqual(rc, 0, log)
            self.assertNotIn('PUSH BLOCKED', log)
            self.assertEqual(self._ahead(root), 0,
                             'stale stamp froze the push — fail-open broken: '
                             + log)


if __name__ == '__main__':
    unittest.main()
