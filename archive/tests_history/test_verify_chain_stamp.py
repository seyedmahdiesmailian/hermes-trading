"""review 2026-09-17 row 2 — the verify chain must never silently go stale.

Report (§1.2): the last verifier stamp was 2026-09-10 with verdict BROKEN
(1706 tests); every commit after it — including the then-HEAD — was pushed
with NO stamp at all, i.e. the b45 push gate fail-opened for a week and
nobody noticed. The self-verification machinery (b44/b50/b51) is well
designed; what was missing is any IN-REPO tripwire that reads the COMMITTED
stamp and cries foul when it stops describing reality.

What can be pinned without rotting on a fresh clone (the b93 lesson —
time-based pins break on any box that is not the production machine):

  * SHAPE  — the stamp is a dict with the four-state verdict vocabulary,
             an ISO-Z 'at', and an int-or-None test count.
  * ROOTED — the stamped sha is a commit that EXISTS in this history. A
             stamp naming a tree outside this repo's history means the
             file was hand-edited or the history was rewritten under it.
  * ORDER  — 'at' never lies in the future (a clock-skewed stamp would
             poison the freshness window of the b45 gate).

What deliberately is NOT pinned: the stamp's AGE. A clone is always older
than the production stamp, and a staleness pin would go red on every
foreign checkout exactly like b93/b94 — the failure mode this repo already
catalogued. Staleness is the live box's autopilot problem (b51
start-verify), surfaced there, not here.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engines import head_verify  # noqa: E402

STAMP = REPO / 'data' / 'ops' / 'head_verified.json'
VERDICTS = head_verify.VERDICTS


def _git(*args: str):
    return subprocess.run(['git', '-C', str(REPO), *args],
                          capture_output=True, text=True, timeout=120)


class StampShapePinned(unittest.TestCase):
    def setUp(self):
        if not STAMP.exists():
            self.skipTest('no committed verifier stamp in this tree')

    def _read(self) -> dict:
        import json
        with open(STAMP, encoding='utf-8') as fh:
            return json.load(fh)

    def test_verdict_uses_the_four_state_vocabulary(self):
        v = self._read().get('verdict')
        self.assertIn(v, VERDICTS,
                      f'stamp verdict {v!r} is outside the b49 vocabulary '
                      f'{VERDICTS} — a hand-edit or a format drift')

    def test_timestamp_is_iso_z_and_not_in_the_future(self):
        at = str(self._read().get('at') or '')
        parsed = datetime.strptime(at, '%Y-%m-%dT%H:%M:%SZ').replace(
            tzinfo=timezone.utc)
        skew = (datetime.now(timezone.utc) - parsed).total_seconds()
        self.assertGreaterEqual(skew, -300,
                                'the stamp claims to be from the future — '
                                'a clock skew poisons the b45 freshness '
                                'window (fresh BROKEN would block pushes)')

    def test_test_count_is_int_or_none(self):
        tests = self._read().get('tests')
        self.assertTrue(tests is None or isinstance(tests, int),
                        f'tests={tests!r} — the anti-vacuity count broke')

    def test_stamped_sha_exists_in_this_history(self):
        sha = str(self._read().get('sha') or '')
        self.assertTrue(sha, 'stamp carries no sha')
        exists = _git('cat-file', '-e', sha)
        if exists.returncode != 0:
            self.skipTest(
                f'shallow clone: stamped sha {sha[:7]} not fetched — '
                f'unshallow (git fetch --unshallow) to check ancestry')
        ancestor = _git('merge-base', '--is-ancestor', sha, 'HEAD')
        self.assertEqual(ancestor.returncode, 0,
                         f'the verifier stamp names {sha[:7]} which EXISTS '
                         f'but is NOT an ancestor of HEAD — history was '
                         f'rewritten under the stamp or the stamp was '
                         f'copied from another repo')


class StampSeamPinned(unittest.TestCase):
    """The machinery contract the stamp depends on (cheap source pins)."""

    def test_stamp_path_goes_through_the_paths_seam(self):
        # b39: an import-time constant would write to production data even
        # from a redirected tree — the seam is call-time
        from engines import paths
        self.assertEqual(head_verify.stamp_path(),
                         paths.data_dir() / 'ops' / 'head_verified.json')

    def test_verify_head_script_still_stamps(self):
        src = (REPO / 'scripts' / 'verify_head.sh').read_text(encoding='utf-8')
        self.assertIn('HERMES_STAMP=1', src,
                      'verify_head.sh no longer asks head_verify to stamp — '
                      'the chain would run forever without recording')

    def test_push_gate_reads_the_stamp_before_pushing(self):
        src = (REPO / 'scripts' / 'git_sync.sh').read_text(encoding='utf-8')
        self.assertIn('push-gate', src,
                      'git_sync.sh no longer consults the b45 gate')


if __name__ == '__main__':
    unittest.main(verbosity=2)
