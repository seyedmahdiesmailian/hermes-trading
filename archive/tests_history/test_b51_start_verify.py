"""b51 — a crashed run must not leave HEAD unverified until the gate fails open.

Real incident shape: the autopilot procedure runs verify_head.sh as step 4b
AFTER the commit. If the run dies between step 4 and 4b (or an operator
commits by hand), the fresh HEAD carries no stamp — and git_sync's
DELIBERATE fail-open (b45: a dead verifier must not freeze backups) pushes
that unverified commit once the old stamp ages out (~1h). The one guard
against shipping a broken HEAD to GitHub had a hole exactly where the
procedure is most fragile: the gap between commit and verification.

Fix (this item): autopilot.sh asks engines/head_verify.py `start-verify` at
run START. When it answers needed (unpushed commits exist, or the stamp
names a different sha than HEAD), the run executes verify_head.sh
immediately — a crashed run heals its own verification on the next tick and
the push gate closes again before the fail-open window can ship the commit.

Deliberate exclusion (b37 alert-hygiene lesson): if HEAD already carries a
non-OK verdict (BROKEN/TIMEOUT/ERROR), the run does NOT re-verify — that
would page ops every hour for the same known-broken commit. The fix for a
BROKEN HEAD is a new commit, which flips the sha-mismatch clause.

Pinned here:
  * decide_start_verify — the pure rule, every branch its own signature;
  * unpushed_count against REAL throwaway repos (pushed=0, ahead=1, no
    origin ref=None — None must never read as 0);
  * the CLI contract (stdout JSON {needed, reason}, exit 0=verify/1=skip)
    run as a subprocess with cwd=throwaway repo — replaying the b45 lesson
    that the decision resolves HEAD from the CALLER's cwd, not the code's;
  * autopilot.sh wiring tripwire: the heal block exists, captures SV_RC
    immediately (b44), runs verify_head.sh on rc=0, never blocks the run
    (no exit, no blind || true — b49), and sits BEFORE the harvest block
    and before the agent launch.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'tests'))

import hermetic  # noqa: E402
from engines import head_verify  # noqa: E402

HEAD_SHA = 'a' * 40
OTHER_SHA = 'b' * 40


def _stamp(verdict='OK', sha=HEAD_SHA):
    at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {'sha': sha, 'verdict': verdict, 'at': at}


class DecideStartVerify(unittest.TestCase):
    """The pure rule — three outcomes, three signatures (b49 posture)."""

    def test_verified_and_pushed_skips(self):
        d = head_verify.decide_start_verify(_stamp(), HEAD_SHA, 0)
        self.assertFalse(d['needed'])
        self.assertIn('already verified', d['reason'])

    def test_unpushed_commits_reverify_even_when_stamped_ok(self):
        # The stale-stamp hole: HEAD is verified OK but git_sync cannot push
        # (network/remote down); in ~1h the gate fail-opens. Re-verifying
        # each run while commits sit unpushed keeps the stamp fresh.
        d = head_verify.decide_start_verify(_stamp(), HEAD_SHA, 2)
        self.assertTrue(d['needed'])
        self.assertIn('ahead of origin', d['reason'])

    def test_stamp_for_other_sha_needs_verification(self):
        # The crashed-run shape: commit landed, step 4b never ran.
        d = head_verify.decide_start_verify(_stamp(sha=OTHER_SHA),
                                            HEAD_SHA, 0)
        self.assertTrue(d['needed'])
        self.assertIn('never verified', d['reason'])

    def test_no_stamp_at_all_needs_verification(self):
        # Hand commit on a box that never ran the verifier.
        for empty in (None, {}, 'garbage'):
            d = head_verify.decide_start_verify(empty, HEAD_SHA, 0)
            self.assertTrue(d['needed'], f'{empty!r} must trigger a heal')
            self.assertIn('never verified', d['reason'])

    def test_broken_head_is_not_reverified_every_hour(self):
        # Alert hygiene: HEAD already carries the verdict; re-running would
        # page ops every tick for the same broken commit. A NEW commit
        # (sha mismatch) re-arms verification instead.
        for v in ('BROKEN', 'TIMEOUT', 'ERROR'):
            d = head_verify.decide_start_verify(_stamp(verdict=v),
                                                HEAD_SHA, 3)
            self.assertFalse(d['needed'], f'{v} HEAD must not re-page')
            self.assertIn(v, d['reason'])

    def test_broken_old_sha_still_heals_new_head(self):
        d = head_verify.decide_start_verify(_stamp(verdict='BROKEN',
                                                   sha=OTHER_SHA),
                                            HEAD_SHA, 0)
        self.assertTrue(d['needed'])

    def test_unresolvable_head_skips_fail_safe(self):
        d = head_verify.decide_start_verify(_stamp(), None, 1)
        self.assertFalse(d['needed'])
        self.assertIn('fail-safe', d['reason'])

    def test_ahead_none_degrades_to_stamp_clause(self):
        # No origin/master ref: 'unknown' must not masquerade as 'pushed'
        # (would skip the heal) NOR as 'ahead' (would always re-verify).
        d = head_verify.decide_start_verify(_stamp(), HEAD_SHA, None)
        self.assertFalse(d['needed'])
        d2 = head_verify.decide_start_verify(_stamp(sha=OTHER_SHA),
                                             HEAD_SHA, None)
        self.assertTrue(d2['needed'])


class UnpushedCount(unittest.TestCase):
    """Real git repos — the three states the reader can return."""

    def _mk_repo(self, tmp, with_origin=True):
        root = Path(tmp) / 'repo'
        root.mkdir(parents=True)
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t',
                   GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')

        def g(*a):
            return subprocess.run(['git', *a], cwd=str(root), env=env,
                                  check=True, capture_output=True)
        g('init', '-q', '-b', 'master')
        (root / 'a.txt').write_text('1')
        g('add', '-A')
        g('commit', '-qm', 'base')
        if with_origin:
            remote = Path(tmp) / 'origin.git'
            subprocess.run(['git', 'init', '--bare', '-q', str(remote)],
                           check=True)
            g('remote', 'add', 'origin', str(remote))
            g('push', '-q', 'origin', 'master')
            (root / 'a.txt').write_text('2')
            g('commit', '-qam', 'unpushed')
        return root

    def test_counts_ahead_pushed_and_missing_origin(self):
        with tempfile.TemporaryDirectory(prefix='hermes_b51_') as tmp:
            ahead_root = self._mk_repo(tmp)
            self.assertEqual(head_verify.unpushed_count(ahead_root), 1)
            subprocess.run(['git', 'push', '-q', 'origin', 'master'],
                           cwd=str(ahead_root), check=True)
            self.assertEqual(head_verify.unpushed_count(ahead_root), 0)
            bare_root = self._mk_repo(Path(tmp) / 'second',
                                      with_origin=False)
            self.assertIsNone(head_verify.unpushed_count(bare_root))

    def test_non_repo_is_none_never_a_raise(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(head_verify.unpushed_count(td))


class StartVerifyCli(unittest.TestCase):
    """The contract autopilot.sh depends on: stdout is ONE JSON line, exit
    0=verify now / 1=skip. Run with cwd=THROWAWAY repo — replaying the b45
    lesson that the decision must resolve HEAD from the CALLER's cwd, not
    from wherever the code lives."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = hermetic.use_temp_data_root()

    @classmethod
    def tearDownClass(cls):
        hermetic.release()

    def _run(self, cwd=None):
        env = dict(os.environ)
        env['HERMES_DATA_ROOT'] = str(self.tmp)
        return subprocess.run(
            [sys.executable, str(REPO / 'engines' / 'head_verify.py'),
             'start-verify'],
            capture_output=True, text=True, timeout=60, env=env,
            cwd=str(cwd or REPO))

    def test_no_stamp_requests_verification_for_caller_head(self):
        p = head_verify.stamp_path()
        if p.exists():
            p.unlink()
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        payload = json.loads(r.stdout)
        self.assertTrue(payload['needed'])
        # reason depends on the live repo's push state (ahead>0 → 'ahead of
        # origin', else 'never verified') — both are heal answers.
        self.assertTrue(payload['reason'])

    def test_ok_stamp_for_head_skips(self):
        head = head_verify.resolve_sha('HEAD', REPO)
        head_verify.write_stamp(head, 'OK', tests=407, seconds=60.0)
        # also make 'ahead' zero for the real repo state: if the live repo
        # has unpushed commits the rule says re-verify — pin the branch we
        # are actually testing by checking the reason matches the state.
        r = self._run()
        payload = json.loads(r.stdout)
        ahead = head_verify.unpushed_count(REPO)
        if ahead:
            self.assertTrue(payload['needed'])
            self.assertIn('ahead of origin', payload['reason'])
        else:
            self.assertEqual(r.returncode, 1, 'verified+pushed must skip')
            self.assertFalse(payload['needed'])

    def test_cli_never_raises_on_garbage_stamp(self):
        p = head_verify.stamp_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{not json', encoding='utf-8')
        r = self._run()
        self.assertIn(r.returncode, (0, 1), r.stderr[-400:])
        payload = json.loads(r.stdout)
        self.assertIn('needed', payload)

    def test_decision_resolves_head_from_caller_cwd(self):
        """The b45 lesson replayed: point the CLI at a THROWAWAY repo whose
        HEAD differs from the code repo's HEAD. With a stamp naming the
        throwaway sha, the answer must be SKIP (it matched the caller's
        HEAD) — proving HEAD is read from cwd, not from the code tree."""
        with tempfile.TemporaryDirectory(prefix='hermes_b51_cwd_') as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            env = dict(os.environ, GIT_AUTHOR_NAME='t',
                       GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t',
                       GIT_COMMITTER_EMAIL='t@t')

            def g(*a):
                subprocess.run(['git', *a], cwd=str(root), env=env,
                               check=True, capture_output=True)
            g('init', '-q', '-b', 'master')
            (root / 'a.txt').write_text('1')
            g('add', '-A')
            g('commit', '-qm', 'base')
            sha = subprocess.run(['git', 'rev-parse', 'HEAD'],
                                 cwd=str(root), capture_output=True,
                                 text=True).stdout.strip()
            self.assertNotEqual(sha, head_verify.resolve_sha('HEAD', REPO),
                                'throwaway HEAD must differ from code HEAD')
            head_verify.write_stamp(sha, 'OK', tests=1, seconds=1.0)
            r = self._run(cwd=root)
            payload = json.loads(r.stdout)
            self.assertFalse(payload['needed'],
                             'gate certified the WRONG tree (b45 disease): '
                             + payload['reason'])


class AutopilotShHealWiring(unittest.TestCase):
    """The bash half: autopilot.sh must ASK and HEAL, never block."""

    SRC = (REPO / 'scripts' / 'autopilot.sh').read_text(encoding='utf-8')

    def _code_lines(self, start_marker, end_marker):
        seg = self.SRC[self.SRC.index(start_marker):self.SRC.index(
            end_marker)]
        return '\n'.join(l for l in seg.splitlines()
                         if not l.strip().startswith('#'))

    def test_script_asks_the_gate(self):
        self.assertIn('start-verify', self.SRC)
        self.assertIn('engines/head_verify.py start-verify', self.SRC)

    def test_rc_captured_immediately_after_assignment(self):
        # b44: `SV_RC=$?` must sit directly after the command it claims.
        lines = [l.strip() for l in self.SRC.splitlines() if l.strip()]
        for k, l in enumerate(lines):
            if l == 'SV_RC=$?':
                self.assertIn('start-verify', lines[k - 1],
                              'SV_RC=$? no longer follows the gate call')

    def test_heal_runs_verify_head_on_needed(self):
        code = self._code_lines('SV="$(', '# b47: HARVEST')
        self.assertIn('bash scripts/verify_head.sh', code,
                      'rc=0 branch must actually run the verifier')
        self.assertIn('b51', code, 'the heal must be loud in the log')

    def test_block_never_kills_the_run(self):
        code = self._code_lines('SV="$(', '# b47: HARVEST')
        self.assertNotIn('exit', code,
                         'a broken heal must LOG, never kill the run')
        self.assertNotIn('|| true', code,
                         'blind || true would make BROKEN == SKIP (b49)')

    def test_heal_happens_before_harvest_and_agent(self):
        # ordering: start-verify < harvest < agent launch — the tree the
        # harvest may commit must sit on a verified base.
        self.assertLess(self.SRC.index('start-verify'),
                        self.SRC.index('autopilot_harvest.py'))
        self.assertLess(self.SRC.index('autopilot_harvest.py'),
                        self.SRC.index('"$HERMES_BIN" -z'))

    def test_bash_case_semantics_replayed(self):
        """Prove the exact shell shape behaves: rc 0 → heal branch, rc 1 →
        silent, rc 2 → loud broken branch."""
        snippet = (
            'case "$1" in\n'
            '  0) echo HEAL ;;\n'
            '  1) : ;;\n'
            '  *) echo BROKEN ;;\n'
            'esac\n')
        for arg, expect in (('0', 'HEAL'), ('1', ''), ('2', 'BROKEN')):
            r = subprocess.run(['bash', '-c', snippet, 'b51', arg],
                               capture_output=True, text=True)
            self.assertEqual(r.stdout.strip(), expect)


class HealEndToEnd(unittest.TestCase):
    """The crashed-run scenario replayed for real: a throwaway repo with a
    local bare origin, one UNPUSHED commit, no stamp → the decision says
    heal; stamp it OK → decision says skip; the push gate meanwhile blocks
    (sha mismatch) so nothing unverified can reach origin in the gap."""

    def test_unverified_fresh_head_heals_then_gates(self):
        with tempfile.TemporaryDirectory(prefix='hermes_b51_e2e_') as tmp:
            root = Path(tmp) / 'repo'
            remote = Path(tmp) / 'origin.git'
            subprocess.run(['git', 'init', '--bare', '-q', str(remote)],
                           check=True)
            root.mkdir()
            env = dict(os.environ, GIT_AUTHOR_NAME='t',
                       GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t',
                       GIT_COMMITTER_EMAIL='t@t')

            def g(*a):
                subprocess.run(['git', *a], cwd=str(root), env=env,
                               check=True, capture_output=True)
            g('init', '-q', '-b', 'master')
            (root / 'a.txt').write_text('1')
            g('add', '-A')
            g('commit', '-qm', 'base')
            g('remote', 'add', 'origin', str(remote))
            g('push', '-q', 'origin', 'master')
            (root / 'a.txt').write_text('2')
            g('commit', '-qam', 'crashed run: committed, never verified')
            sha = subprocess.run(['git', 'rev-parse', 'HEAD'],
                                 cwd=str(root), capture_output=True,
                                 text=True).stdout.strip()

            data_root = Path(tmp) / 'state'
            ops = data_root / 'data' / 'ops'
            ops.mkdir(parents=True)
            env2 = dict(os.environ, HERMES_DATA_ROOT=str(data_root))

            def ask(mode):
                return subprocess.run(
                    [sys.executable,
                     str(REPO / 'engines' / 'head_verify.py'), mode],
                    cwd=str(root), env=env2, capture_output=True,
                    text=True, timeout=60)

            # 1. no stamp + unpushed commit → start-verify says HEAL
            r = ask('start-verify')
            self.assertEqual(r.returncode, 0, r.stderr[-300:])
            payload = json.loads(r.stdout)
            self.assertTrue(payload['needed'])
            self.assertIn('ahead of origin', payload['reason'])
            # 2. meanwhile the push gate BLOCKS (sha mismatch, fresh stamp
            #    absent → fail-open would push; with an old-sha OK stamp it
            #    refuses) — simulate the pre-heal state honestly:
            (ops / 'head_verified.json').write_text(json.dumps(
                {'sha': 'c' * 40, 'verdict': 'OK',
                 'at': datetime.now(timezone.utc)
                 .strftime('%Y-%m-%dT%H:%M:%SZ')}), encoding='utf-8')
            r = ask('push-gate')
            self.assertEqual(r.returncode, 1,
                             'gate let an unverified HEAD through')
            # 3. the heal ran (stamp now names THIS sha, OK). Two facts now
            #    coexist: the push gate ALLOWS (verified OK for HEAD), and
            #    start-verify still says needed because ahead=1 — re-
            #    verifying each run while commits sit unpushed keeps the
            #    stamp fresh so the gate can never fail-open mid-block.
            (ops / 'head_verified.json').write_text(json.dumps(
                {'sha': sha, 'verdict': 'OK',
                 'at': datetime.now(timezone.utc)
                 .strftime('%Y-%m-%dT%H:%M:%SZ')}), encoding='utf-8')
            r = ask('start-verify')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr[-300:])
            self.assertTrue(json.loads(r.stdout)['needed'],
                            'ahead=1 must keep re-stamping freshness')
            self.assertIn('ahead of origin', json.loads(r.stdout)['reason'])
            r = ask('push-gate')
            self.assertEqual(r.returncode, 0, r.stdout)
            # 4. once pushed (ahead=0) and stamped OK, the run goes quiet.
            subprocess.run(['git', 'push', '-q', 'origin', 'master'],
                           cwd=str(root), env=env, check=True)
            r = ask('start-verify')
            self.assertEqual(r.returncode, 1,
                             'verified+pushed HEAD must not re-verify: '
                             + r.stdout)
            self.assertFalse(json.loads(r.stdout)['needed'])


if __name__ == '__main__':
    unittest.main()
