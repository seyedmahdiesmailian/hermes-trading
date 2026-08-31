"""b39 — no production module may bind a STATE path at import time.

Why this file exists: engines.paths exists precisely so that setting
HERMES_DATA_ROOT (tests via hermetic, staging boxes via env) redirects the
whole state tree — but that only works if the path is resolved at CALL time.
Three modules broke the rule and the break was invisible:

  * hermes_master.py   LOG_FILE / REPORT_FILE — any test importing the master
                     appended to production logs/master.log. The comment
                     above those lines literally claimed the opposite ("so a
                     test run can never write into production logs").
  * notifier/telegram  LOG_DIR — every real _send() wrote production
                     logs/telegram_messages.log.
  * position_daemon    LOG_FILE — dead constant (log() already resolved per
                     call), but a trap for the next caller.

The class is worse than "a test writes a log line": the same pattern in a
STATE writer lets a test overwrite current_plan.json / kill_switch_state.json
— which is exactly the 2026-08-30 incident described in engines/paths.py.

METHOD: the check runs in a FRESH SUBPROCESS with HERMES_DATA_ROOT pointed at
a temp dir. In-process is unsound — unittest discovery imports every test
module first, so production modules are already in sys.modules and their
import-time code never re-runs; the test would pass while the bug stayed.

Deliberate exclusions live in ALLOWED with a reason; an exclusion without a
reason is a bug waiting to be filed, and test_allowed_entries_are_still_real
fails if one goes stale.
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, '/home/ai/hermes-trading')

REPO = Path('/home/ai/hermes-trading')
PROD = REPO / 'data'
PROD_LOGS = REPO / 'logs'

# module.attr -> why a production-root path here is harmless.
# b39 cleanup: the hermes_runtime BASE_DIR/DATA_DIR/PLAN_DIR aliases,
# notifier.telegram.BASE_DIR and hermes_master.BASE_DIR are GONE (converted
# to call-time accessors), so their exemptions went with them —
# test_allowed_entries_are_still_real is what caught that drift.
ALLOWED = {
    # Code location, not state: never written to, and scripts use it to find
    # .env / sibling files. Redirecting it would be wrong, not a bug.
    'notifier.dashboards.ROOT': 'code root — reads below resolve state paths '
                                'from it, but every WRITER in this module now '
                                'goes through _pause_flag()/_audit_log() (b39)',
    'notifier.dashboards.DATA': 'read-only dashboards readers (_j()/csv) — an '
                                'operator panel must show the REAL numbers even '
                                'from a test run; never written',
}

# The child program: import every production module under the temp root and
# report any module-level Path constant that still points at production.
_CHILD = r'''
import importlib, json, os, sys
from pathlib import Path
sys.path.insert(0, r"%(repo)s")
root = Path(os.environ["HERMES_DATA_ROOT"])
prod = [r"%(prod)s", r"%(prod_logs)s"]
mods, offenders = [], []
for p in sorted(Path(r"%(repo)s").glob("*.py")):
    mods.append(p.stem)
for pkg in ("engines", "notifier"):
    for p in sorted((Path(r"%(repo)s") / pkg).glob("*.py")):
        if p.name != "__init__.py":
            mods.append(pkg + "." + p.stem)
for name in mods:
    try:
        m = importlib.import_module(name)
    except ImportError:
        continue
    except Exception as e:
        offenders.append({"key": name, "attr": None, "path": None,
                          "why": "import raised " + repr(e)[:200]})
        continue
    for attr in dir(m):
        if attr.startswith("__"):
            continue
        v = getattr(m, attr)
        if not isinstance(v, Path):
            continue
        s = str(v)
        if any(s.startswith(x) for x in prod):
            offenders.append({"key": name + "." + attr, "attr": attr,
                              "path": s, "why": "binds a production state path "
                              "at import time"})
print(json.dumps({"n_mods": len(mods), "offenders": offenders}))
'''


class NoImportTimeStatePaths(unittest.TestCase):
    """The tripwire, executed in a clean interpreter."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='hermes_b39_')
        env = dict(os.environ)
        env['HERMES_DATA_ROOT'] = cls.tmp.name
        cls.proc = subprocess.run(
            [sys.executable, '-c', _CHILD % {'repo': str(REPO),
                                             'prod': str(PROD),
                                             'prod_logs': str(PROD_LOGS)}],
            capture_output=True, text=True, timeout=180, env=env, cwd=str(REPO))
        cls.payload = {}
        for line in reversed(cls.proc.stdout.strip().splitlines()):
            if line.startswith('{'):
                cls.payload = json.loads(line)
                break

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_child_ran_and_covered_the_tree(self):
        self.assertEqual(self.proc.returncode, 0,
                         f'child crashed: {self.proc.stderr[-2000:]}')
        self.assertGreater(self.payload.get('n_mods', 0), 25,
                           'the tripwire must cover the production tree, got '
                           f"{self.payload.get('n_mods')} modules")

    def test_no_module_state_constant_points_at_production(self):
        offenders = [o for o in self.payload.get('offenders', [])
                     if o['key'] not in ALLOWED]
        self.assertEqual(
            offenders, [],
            'b39: these module-level constants bind a PRODUCTION state path at '
            'import time, so HERMES_DATA_ROOT cannot redirect them — resolve at '
            'call time (see engines/paths.py) or add a justified ALLOWED entry: '
            + '; '.join(f"{o['key']}={o.get('path')} {o.get('why')}"
                        for o in offenders))

    def test_allowed_entries_are_still_real_paths(self):
        """A dead ALLOWED key must not linger as a silent exemption for a
        future re-introduction of the same attribute. Checked by hasattr, not
        by offender-membership: some exemptions (code-root constants) never
        bind a data/logs path and so never appear as offenders anyway."""
        stale = []
        for key in ALLOWED:
            mod_name, _, attr = key.rpartition('.')
            try:
                mod = importlib.import_module(mod_name)
            except Exception:
                stale.append(f'{key}: module {mod_name} gone')
                continue
            if not hasattr(mod, attr):
                stale.append(f'{key}: attribute gone')
        self.assertEqual(stale, [],
                         'remove dead ALLOWED entries: ' + '; '.join(stale))


class NotifierLogDirIsCallTime(unittest.TestCase):
    """The specific leak b39 found in notifier.telegram._send."""

    def test_send_writes_under_the_redirected_root(self):
        sys.path.insert(0, str(REPO / 'tests'))
        import hermetic
        hermetic.use_temp_data_root()
        try:
            import notifier.telegram as tg
            root = Path(os.environ['HERMES_DATA_ROOT'])
            # No token in this env → _send logs the message and returns False
            # WITHOUT touching the network. That write is what we assert on.
            for k in ('TELEGRAM_BOT_TOKEN', 'AUTOPILOT_REPORT_BOT_TOKEN'):
                self.addCleanup(os.environ.pop, k, None)
                os.environ[k] = ''
            self.assertFalse(tg.send_telegram('b39 probe message'))
            log = root / 'logs' / 'telegram_messages.log'
            self.assertTrue(log.exists(),
                            'the message log must land under the temp root')
            self.assertIn('b39 probe message', log.read_text(encoding='utf-8'))
        finally:
            hermetic.release()

    def test_production_telegram_log_has_no_test_traffic(self):
        prod_log = PROD_LOGS / 'telegram_messages.log'
        if not prod_log.exists():
            self.skipTest('no production telegram log yet')
        self.assertNotIn('b39 probe message',
                         prod_log.read_text(encoding='utf-8'),
                         'a test wrote into the production telegram log')


class DashboardsWritersAreCallTime(unittest.TestCase):
    """b39: the operator-control WRITERS (pause flag + audit log) must follow
    the active data root. The tripwire catches a re-introduced module
    constant; this pins the behaviour itself — a test or staging run that
    exercises auto:pause must never toggle the REAL autopilot pause."""

    def test_pause_flag_and_audit_log_follow_the_redirected_root(self):
        sys.path.insert(0, str(REPO / 'tests'))
        import hermetic
        hermetic.use_temp_data_root()
        try:
            from notifier import dashboards as d
            root = Path(os.environ['HERMES_DATA_ROOT'])
            self.assertEqual(d._pause_flag(),
                             root / 'data' / 'ops' / 'autopilot_paused')
            self.assertEqual(d._audit_log(),
                             root / 'logs' / 'control_audit.log')
            # _audit() must actually land under the temp root
            d._audit('b39 probe', 'OK')
            self.assertIn('b39 probe',
                          (root / 'logs' / 'control_audit.log')
                          .read_text(encoding='utf-8'))
            self.assertNotIn('b39 probe',
                             (PROD_LOGS / 'control_audit.log')
                             .read_text(encoding='utf-8')
                             if (PROD_LOGS / 'control_audit.log').exists()
                             else '',
                             'a test wrote into the production control audit log')
        finally:
            hermetic.release()


class MasterLogPathsAreCallTime(unittest.TestCase):
    """b37 found it, b39 pins it: hermes_master must not write production logs."""

    def test_log_and_report_resolve_under_the_temp_root(self):
        sys.path.insert(0, str(REPO / 'tests'))
        import hermetic
        hermetic.use_temp_data_root()
        try:
            import hermes_master as hm
            root = Path(os.environ['HERMES_DATA_ROOT'])
            hm.log('b39 master probe')
            hm.save_report('b39 report probe')
            self.assertIn('b39 master probe',
                          (root / 'logs' / 'master.log').read_text(encoding='utf-8'))
            self.assertIn('b39 report probe',
                          (root / 'logs' / 'report.txt').read_text(encoding='utf-8'))
            prod_log = PROD_LOGS / 'master.log'
            if prod_log.exists():
                self.assertNotIn('b39 master probe',
                                 prod_log.read_text(encoding='utf-8'),
                                 'b39: the master still writes production logs')
        finally:
            hermetic.release()


if __name__ == '__main__':
    unittest.main()
