"""b40 — guard-degradation alert state must be OBSERVABLE, not write-only.

Background: b37 made hermes_master WRITE data/ops/guard_alert_state.json
when the fallback management path loses its news_lock/time_exit guards, but
NOTHING read the file — a degraded management path was visible only in the
ops chat, and the page itself is deduped to 1 per 6h. b40 adds the single
canonical reader (engines/guard_status) and wires it into the ops dashboards
(home verdict, autopilot panel, trader risk panel, trader home), the daily
digest, and the master report.

These tests pin:
  * the WRITER→READER contract (alert_degraded_guards output is readable and
    normalized) — the b34 lesson: two modules, one fact, one seam;
  * staleness semantics (an absent guards key never clears the file, so a
    recovered degradation can linger — the reader must say "last observed",
    never claim "broken right now");
  * fail-safe display (missing/corrupt/foreign-shaped files → no line, no
    crash — display is the one place that must never raise);
  * every panel actually renders the line when degraded and hides it when
    clean;
  * the digest script (run in a subprocess under a temp root) includes it;
  * a tripwire: no production module may hand-parse the file again.
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

# b41 discipline: this file patches notifier.telegram.send_ops (via the
# writer tests) — hermes_master must be imported BEFORE any patch window so
# its module-level copy of send_ops is the real one.
import hermes_master  # noqa: E402,F401
from engines import guard_status  # noqa: E402

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _write_state(payload: dict):
    p = guard_status.state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding='utf-8')


class WriterReaderContract(unittest.TestCase):
    """The file hermes_master writes must be exactly what the reader parses."""

    def setUp(self):
        hermetic.use_temp_data_root()

    def tearDown(self):
        hermetic.release()

    def _capture_ops(self):
        import notifier.telegram as tg
        real = tg.send_ops
        self.addCleanup(lambda: setattr(tg, 'send_ops', real))
        sent = []
        tg.send_ops = lambda msg: sent.append(msg) or True
        return sent

    def test_writer_output_is_readable_and_normalized(self):
        sent = self._capture_ops()
        self.assertTrue(hermes_master.alert_degraded_guards(
            {'guards': {'state': 'error', 'detail': 'AttributeError: x'}},
            'manage', now=NOW))
        self.assertEqual(len(sent), 1)
        rec = guard_status.read(now=NOW + timedelta(minutes=15))
        self.assertIsNotNone(rec, 'the reader must see what the writer wrote')
        self.assertEqual(rec['state'], 'error')
        self.assertEqual(rec['step'], 'manage')
        self.assertIn('AttributeError', rec['detail'])
        self.assertFalse(rec['stale'])
        self.assertAlmostEqual(rec['age_sec'], 900, delta=2)
        line = guard_status.describe(rec)
        self.assertIn('خطای محاسبهٔ گارد', line)
        self.assertIn('step=manage', line)
        self.assertIn('پیش', line)

    def test_healthy_cycle_clears_the_file_and_the_line(self):
        self._capture_ops()
        hermes_master.alert_degraded_guards(
            {'guards': {'state': 'calendar_unavailable'}}, 'manage', now=NOW)
        self.assertIsNotNone(guard_status.read(now=NOW))
        hermes_master.alert_degraded_guards(
            {'guards': {'state': 'applied'}}, 'manage', now=NOW)
        self.assertIsNone(guard_status.read(now=NOW))
        self.assertEqual(guard_status.describe(None), '')

    def test_cooldown_constant_is_shared_not_duplicated(self):
        # drift guard: the writer's throttle and the reader's staleness math
        # must come from the same number (b34's "two modules, one fact").
        self.assertEqual(hermes_master.GUARD_ALERT_COOLDOWN_SEC,
                         guard_status.GUARD_ALERT_COOLDOWN_SEC)
        self.assertEqual(str(hermes_master._guard_alert_state()),
                         str(guard_status.state_path()))


class ReaderFailSafe(unittest.TestCase):
    def setUp(self):
        hermetic.use_temp_data_root()

    def tearDown(self):
        hermetic.release()

    def test_missing_file_is_none(self):
        self.assertIsNone(guard_status.read())

    def test_corrupt_file_is_none_not_crash(self):
        p = guard_status.state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{not json', encoding='utf-8')
        self.assertIsNone(guard_status.read())

    def test_foreign_shape_without_state_is_none(self):
        _write_state({'key': 'x', 'at': NOW.isoformat()})  # no 'state'
        self.assertIsNone(guard_status.read())

    def test_unknown_state_still_surfaces(self):
        """Fail-loud bias: a future third degraded state must not become
        invisible because STATE_FA was never updated."""
        _write_state({'state': 'brand_new_failure', 'step': 'manage',
                      'detail': 'x', 'at': NOW.isoformat()})
        rec = guard_status.read(now=NOW + timedelta(minutes=5))
        self.assertIsNotNone(rec)
        self.assertIn('brand_new_failure', guard_status.describe(rec))

    def test_bad_timestamp_reads_as_unknown_age(self):
        _write_state({'state': 'error', 'detail': 'x', 'at': 'yesterday'})
        rec = guard_status.read()
        self.assertIsNotNone(rec)
        self.assertIsNone(rec['age_sec'])
        self.assertFalse(rec['stale'])
        self.assertIn('تاریخ نامعلوم', guard_status.describe(rec))

    def test_stale_record_is_flagged_in_words(self):
        old = NOW - timedelta(seconds=guard_status.STALE_AFTER_SEC + 60)
        _write_state({'state': 'error', 'detail': 'x', 'at': old.isoformat()})
        rec = guard_status.read(now=NOW)
        self.assertTrue(rec['stale'])
        self.assertIn('ممکن است برطرف شده باشد', guard_status.describe(rec))
        # and a fresh one is NOT hedged
        _write_state({'state': 'error', 'detail': 'x',
                      'at': (NOW - timedelta(hours=1)).isoformat()})
        self.assertNotIn('ممکن است', guard_status.describe(
            guard_status.read(now=NOW)))


class PanelIntegration(unittest.TestCase):
    """Every consumer must show the line when degraded, hide it when clean.

    _bridge/_services are patched on dashboards ITSELF (the module under
    test) — the correct binding per b41 — so no test here touches the
    Windows bridge or systemctl.
    """

    def setUp(self):
        hermetic.use_temp_data_root()
        from notifier import dashboards as d
        self.d = d
        self._real = (d._bridge, d._services)
        d._bridge = lambda: (None, {'ok': True, 'balance': 1000.0,
                                    'equity': 1000.0}, {'data': [], 'count': 0})
        d._services = lambda: {'hermes-signal': 'active',
                               'hermes-position': 'active',
                               'hermes-gateway': 'active',
                               'hermes-dashboard': 'active'}
        _write_state({'key': 'error|x', 'state': 'error', 'step': 'manage',
                      'detail': 'AttributeError: boom',
                      'at': (datetime.now(timezone.utc)
                             - timedelta(minutes=5)).isoformat()})

    def tearDown(self):
        self.d._bridge, self.d._services = self._real
        hermetic.release()

    def test_ops_home_verdict_flags_degradation(self):
        ok, problems = self.d._verdict()
        self.assertFalse(ok, 'a degraded guard path is a needs-attention fact')
        self.assertTrue(any('گاردهای مدیریت ضعیف' in p for p in problems),
                        problems)
        text, _ = self.d.ops_home()
        self.assertIn('گاردهای مدیریت ضعیف', text)

    def test_ops_auto_shows_full_line(self):
        text, _ = self.d.ops_render('auto')
        self.assertIn('گاردهای ایمنی مدیریت ضعیف شده', text)
        self.assertIn('step=manage', text)
        self.assertIn('AttributeError: boom', text)

    def test_trade_risk_and_home_show_it(self):
        text, _ = self.d.trade_risk()
        self.assertIn('گاردهای ایمنی مدیریت ضعیف شده', text)
        text, _ = self.d.trade_home()
        self.assertIn('گاردهای مدیریت ضعیف', text)

    def test_clean_state_shows_nothing(self):
        guard_status.state_path().unlink()
        ok, problems = self.d._verdict()
        self.assertTrue(ok, problems)
        for text in (self.d.ops_render('auto')[0],
                     self.d.trade_risk()[0],
                     self.d.trade_home()[0]):
            self.assertNotIn('گاردها', text)

    def test_corrupt_state_never_breaks_a_panel(self):
        guard_status.state_path().write_text('}{', encoding='utf-8')
        text, kb = self.d.ops_render('auto')
        self.assertTrue(text and kb)
        self.assertNotIn('خطا داد', text)


class DigestIntegration(unittest.TestCase):
    """The daily digest runs as a cron script — test it the way cron does:
    fresh subprocess, HERMES_DATA_ROOT redirected, send token blanked so
    load_dotenv's no-override rule makes it PRINT the text instead of
    sending it. (The digest's ROOT/BACKLOG constants are hardcoded
    production paths but are read-only — same ALLOWED class as dashboards.)
    """

    def _run_digest(self):
        env = dict(os.environ)
        env['HERMES_DATA_ROOT'] = os.environ['HERMES_DATA_ROOT']
        env['AUTOPILOT_REPORT_BOT_TOKEN'] = ''
        env['TELEGRAM_BOT_TOKEN'] = ''
        r = subprocess.run([sys.executable, 'scripts/autopilot_digest.py'],
                           capture_output=True, text=True, timeout=90,
                           env=env, cwd=str(REPO))
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        return r.stdout

    def test_digest_includes_degradation_line(self):
        hermetic.use_temp_data_root()
        try:
            _write_state({'key': 'calendar_unavailable|', 'state':
                          'calendar_unavailable', 'step': 'monitor',
                          'detail': 'both feeds failed',
                          'at': (datetime.now(timezone.utc)
                                 - timedelta(hours=2)).isoformat()})
            out = self._run_digest()
            self.assertIn('گاردهای ایمنی مدیریت ضعیف شده', out)
            self.assertIn('تقویم اخبار دیده نشد', out)
        finally:
            hermetic.release()

    def test_digest_clean_when_no_state(self):
        hermetic.use_temp_data_root()
        try:
            out = self._run_digest()
            self.assertNotIn('گاردها', out)
            self.assertIn('گزارش خودکار', out)  # digest itself still built
        finally:
            hermetic.release()


class SingleSeamTripwire(unittest.TestCase):
    """b34/b41 lesson, applied to this file: guard_alert_state.json had one
    writer and zero readers; the fix must not create five hand-rolled ones.
    Only engines/guard_status.py may name the file; everyone else imports it.
    """

    PROD_DIRS = [REPO / 'engines', REPO / 'notifier']
    PROD_TOP = list(REPO.glob('*.py')) + list((REPO / 'scripts').glob('*.py'))

    def test_only_the_reader_names_the_file(self):
        files = list(self.PROD_TOP)
        for d in self.PROD_DIRS:
            files += sorted(d.glob('*.py'))
        offenders = []
        for f in files:
            if f.name == 'guard_status.py' or 'test' in f.name:
                continue
            try:
                src = f.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            if 'guard_alert_state.json' in src:
                offenders.append(str(f.relative_to(REPO)))
        self.assertEqual(
            offenders, [],
            'b40: guard_alert_state.json must be parsed ONLY by '
            'engines/guard_status.py — import it instead: ' + ', '.join(offenders))


if __name__ == '__main__':
    unittest.main()
