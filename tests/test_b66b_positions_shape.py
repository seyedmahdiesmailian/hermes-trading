"""b66-follow-up — the /api/positions reply has ONE reader, and it is shape-safe.

Found by the b66 clean-worktree verification (verify_head.sh on the harvest
commit): with no .env in the worktree there is no bridge token, so
bridge_client._get() returns {'ok': False, 'error': 'HTTP_401', 'data': {...}}
— `data` a DICT — and notifier/dashboards.trade_home() iterated it, hit the
string KEYS, and died with AttributeError: 'str' object has no attribute
'get'. The panel fell back to '🔴 پنل ... خطا داد' and the unknown-panel
fallback test went RED. b66 did not break this — it REMOVED the accident that
hid it: the old ROOT literal made dashboards load the PRODUCTION .env even
inside an isolated worktree, so the verify run always had a token and always
saw a list. Isolation exposed a real production bug: any bridge auth blip or
MT5 error page while a position panel is open renders an error card on the
operator's home panel, and on the SIGNAL path the same shape degrades the
open-position count to 0 — the already_in_position gate going blind, the b65
'auth failure as empty account' class again.

Pinned here:
  * engines.bridge_payload.positions_list/position_count: every observed
    reply shape maps to the right answer (the b36 fixture builders produce
    the GOOD shape, hand-built payloads produce every BAD one);
  * BEHAVIOURAL: trade_home + trade_positions render (never an error card)
    when the bridge answers 401 with a dict 'data' — replayed through the
    real panels with _bridge patched to the exact crash payload;
  * BEHAVIOURAL: the daemon's live-map build no longer raises on the 401
    shape (source pin + a replay of the comprehension through positions_list);
  * ONE reader: hermes_runtime._positions_list delegates to the shared
    module, and no consumer file may go back to hand-rolling
    `.get('data')` on a positions reply (AST scan of the four consumers).
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines.bridge_payload import positions_list, position_count  # noqa: E402
from tests import fixtures_bridge as fb  # noqa: E402

# The EXACT payload that crashed trade_home in the clean worktree:
# bridge_client._get() on HTTP 401 with a non-JSON body.
CRASH_401 = {'ok': False, 'error': 'HTTP_401',
             'data': {'raw': '<html>401 Unauthorized</html>'}}
# MT5 itself failing: server returns ok=false with a LIST-less body.
CRASH_MT5 = {'ok': False, 'error': "['Common::LastError', 'Generic error']",
             'data': {'raw': 'no mt5'}}


class TestPositionsReader(unittest.TestCase):
    def test_good_shape_from_fixtures(self):
        resp = fb.positions_payload([fb.pos_raw(profit=12.5)])
        self.assertEqual(position_count(resp), 1)
        self.assertEqual(positions_list(resp)[0]['profit'], 12.5)
        self.assertEqual(position_count(fb.positions_payload()), 0)

    def test_401_dict_data_never_yields_strings(self):
        self.assertEqual(positions_list(CRASH_401), [])
        self.assertEqual(position_count(CRASH_401), 0)

    def test_mt5_error_shape(self):
        self.assertEqual(positions_list(CRASH_MT5), [])

    def test_ok_true_but_data_is_dict(self):
        # a bridge build that jsonified a dict body under ok — still no crash
        self.assertEqual(positions_list({'ok': True, 'data': {'a': 1}}), [])

    def test_non_dict_items_filtered(self):
        self.assertEqual(positions_list({'ok': True, 'data': ['x', 1]}), [])

    def test_daemon_leniency_no_ok_key(self):
        # position_daemon's failure guard has always accepted {data:[...]}
        # without ok; reading it as empty would falsely report every tracked
        # ticket CLOSED (duplicate-open hazard) — must stay a LIST.
        self.assertEqual(position_count({'data': [{'ticket': 7}]}), 1)

    def test_garbage_inputs(self):
        for bad in (None, 'x', 42, [], {}, {'data': None}, {'positions': 'x'}):
            self.assertEqual(positions_list(bad), [])


class TestPanelsSurviveAuthFailure(unittest.TestCase):
    """The crash replay: the real panels, the real 401 payload."""

    def _bridge_401(self):
        return None, {'ok': False, 'error': 'HTTP_401'}, CRASH_401

    def test_trade_home_renders_not_error_card(self):
        from notifier import dashboards as d
        with patch.object(d, '_bridge', self._bridge_401):
            text, kb = d.trade_home()
        self.assertIn('هرمس تریدر', text)
        self.assertNotIn('خطا داد', text)
        self.assertIn('Open Positions', text)
        self.assertIn('0 ·', text)   # count reads 0, floating P&L 0.00

    def test_trade_positions_renders_bridge_down_not_crash(self):
        from notifier import dashboards as d
        with patch.object(d, '_bridge',
                          lambda: (None, {'ok': False, 'error': 'HTTP_401'},
                                   CRASH_401)):
            text, kb = d.trade_positions()
        self.assertIn('بریج', text)
        self.assertNotIn('خطا داد', text)

    def test_pos_detail_unknown_ticket_is_graceful(self):
        from notifier import dashboards as d
        with patch.object(d, '_bridge', self._bridge_401):
            text, kb = d.trade_pos_detail('123')
        self.assertIn('باز نیست', text)

    def test_unknown_panel_fallback_still_reaches_home(self):
        """The test that went RED in the clean worktree — replayed directly."""
        from notifier import dashboards as d
        with patch.object(d, '_bridge', self._bridge_401):
            text, kb = d.trade_home()
        self.assertTrue(text.startswith('💹'), text[:40])


class TestOneReader(unittest.TestCase):
    """No consumer may go back to hand-rolling the positions envelope read."""

    CONSUMERS = ('hermes_runtime.py', 'position_daemon.py',
                 'engines/signal_listener.py', 'notifier/dashboards.py')

    def test_runtime_delegates_to_shared_reader(self):
        src = (ROOT / 'hermes_runtime.py').read_text(encoding='utf-8')
        i = src.index('def _positions_list')
        body = src[i:i + 700]
        self.assertIn('positions_list(resp)', body)
        self.assertIn('bridge_payload', body,
                      '_positions_list must DELEGATE, not re-implement')

    def test_consumers_use_the_shared_reader(self):
        for rel in self.CONSUMERS:
            src = (ROOT / rel).read_text(encoding='utf-8')
            self.assertTrue('positions_list' in src or 'position_count' in src,
                            f'{rel} reads a positions reply again?')

    def test_no_direct_data_iteration_on_positions_replies(self):
        """AST: in the four consumer files, no subscript/iteration of the
        form `X.get('data')` may sit directly inside a for/comp iterable
        unless it passes through positions_list. (Cheap shape pin: the exact
        crash sites were `for p in (pos.get('data') or [])` and
        `for p in resp.get('data', [])`.)"""
        offenders = []
        for rel in self.CONSUMERS:
            tree = ast.parse((ROOT / rel).read_text(encoding='utf-8'),
                             filename=rel)
            for node in ast.walk(tree):
                loops = ([node.iter] if isinstance(node, ast.For) else
                         [g.iter for g in node.generators]
                         if isinstance(node, (ast.ListComp, ast.SetComp,
                                              ast.GeneratorExp)) else [])
                for it in loops:
                    txt = ast.unparse(it)
                    if ".get('data')" in txt or '.get("data")' in txt:
                        if 'positions_list' not in txt:
                            offenders.append(f'{rel}:{node.lineno}: {txt}')
        self.assertEqual(offenders, [],
                         'positions reply iterated by hand again — use '
                         'engines.bridge_payload.positions_list')

    def test_pre_fix_crash_shape_replayed_through_the_old_code(self):
        """Anti-vacuity: the OLD comprehension must RAISE on CRASH_401 —
        proof the payload we replay is the one that actually broke HEAD."""
        with self.assertRaises(AttributeError):
            [p.get('profit') for p in (CRASH_401.get('data') or [])
             if str(p.get('profit') or '').isdigit()]
        # and the NEW reader must not:
        self.assertEqual(positions_list(CRASH_401), [])


if __name__ == '__main__':
    unittest.main()
