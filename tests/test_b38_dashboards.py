"""b38: dashboard routing + access control.

The trade-bot buttons are served from the SAME getUpdates loop as signals
(a second poller on that token would 409 and silently drop signals), so the
callback/command plumbing lives in engines.signal_listener and is tested here
with the Telegram API faked out.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('TELEGRAM_CHAT_ID', '194015957')
os.environ['TELEGRAM_CHAT_ID'] = '194015957'

from engines import signal_listener as sl  # noqa: E402


def _cb(chat_id: str, data: str, mid: int = 555) -> dict:
    return {'id': 'q1', 'data': data,
            'message': {'message_id': mid, 'chat': {'id': int(chat_id)}}}


class TradeCallbackTests(unittest.TestCase):
    def _calls(self, cb):
        seen = []
        def fake_api(method, params=None):
            seen.append((method, params or {}))
            return {'ok': True}
        with patch.object(sl, '_telegram_api', side_effect=fake_api):
            sl._serve_trade_callback(cb)
        return seen

    def test_owner_gets_panel_edit(self):
        calls = self._calls(_cb('194015957', 'tr:risk'))
        edit = [c for c in calls if c[0] == 'editMessageText']
        self.assertEqual(len(edit), 1, calls)
        self.assertIn('گیت‌های ایمنی', edit[0][1]['text'])
        kb = json.loads(edit[0][1]['reply_markup'])['inline_keyboard']
        self.assertTrue(any('پلن' in b['text'] for row in kb for b in row))
        self.assertTrue(any(c[0] == 'answerCallbackQuery' for c in calls))

    def test_stranger_is_denied_without_data(self):
        calls = self._calls(_cb('-100999', 'tr:plan'))
        self.assertFalse([c for c in calls if c[0] == 'editMessageText'],
                         'a non-owner chat must never receive panel content')
        ans = [c for c in calls if c[0] == 'answerCallbackQuery']
        self.assertEqual(len(ans), 1)
        self.assertTrue(ans[0][1].get('show_alert'))

    def test_unknown_panel_falls_back_to_home(self):
        calls = self._calls(_cb('194015957', 'tr:does_not_exist'))
        edit = [c for c in calls if c[0] == 'editMessageText']
        self.assertEqual(len(edit), 1)
        self.assertIn('هرمس تریدر', edit[0][1]['text'])

    def test_command_routes_to_panels(self):
        sent = []
        def fake_api(method, params=None):
            sent.append((method, params or {}))
            return {'ok': True}
        for cmd, needle in (('/plan', 'پلن معاملاتی'), ('/positions', 'پوزیشن'),
                            ('/pnl', 'سود و ضرر'), ('/risk', 'گیت‌های ایمنی')):
            sent.clear()
            with patch.object(sl, '_telegram_api', side_effect=fake_api):
                sl._serve_trade_command('194015957', cmd)
            msg = [c for c in sent if c[0] == 'sendMessage']
            self.assertEqual(len(msg), 1, cmd)
            self.assertIn(needle, msg[0][1]['text'], cmd)


class DashboardRendererTests(unittest.TestCase):
    """Every panel must render even with missing state — an operator needs an
    answer while things are broken, not a traceback."""

    def test_all_panels_render_with_garbage_state(self):
        from notifier import dashboards as d
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            real_data, real_root = d.DATA, d.ROOT
            d.ROOT = Path(td)
            d.DATA = Path(td) / 'data'
            (d.DATA / 'xau_plan').mkdir(parents=True)
            (d.DATA / 'ops').mkdir(parents=True)
            (d.DATA / 'xau_plan/current_plan.json').write_text('{ not json')
            try:
                for name in ('home', 'sys', 'auto', 'ops', 'trade'):
                    text, kb = d.ops_render(name)
                    self.assertIsInstance(text, str)
                    self.assertTrue(text, name)
                    self.assertTrue(kb, name)
                for name in ('home', 'plan', 'pos', 'pnl', 'risk'):
                    text, kb = d.trade_render(name)
                    self.assertTrue(text, name)
                    self.assertTrue(kb, name)
            finally:
                d.DATA, d.ROOT = real_data, real_root

    def test_future_expiry_reads_as_countdown(self):
        from notifier import dashboards as d
        from datetime import datetime, timedelta, timezone
        future = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
        self.assertIn('ساعت دیگر', d._ago(future))
        self.assertIn('پیش', d._ago((datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()))


if __name__ == '__main__':
    unittest.main()
