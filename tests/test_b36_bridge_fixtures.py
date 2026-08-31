"""b36 — the shared bridge fixtures must stay FIELD-FOR-FIELD with the producer.

Why this file exists: b34's int('SELL') crash survived to production because
every test fake hand-rolled payloads that never matched the real wire shape
(and never contained a position at all). tests/fixtures_bridge.py is now the
single source of production-shaped payloads; this file is the tripwire that
keeps it honest:

  1. AST-parse scripts/mt5_http_server_v2.py and extract the EXACT response
     keys of /api/positions, /api/tick, /api/account, /api/history/deals and
     the OHLC rows — fail if the fixture field lists drift from the server.
  2. Assert the fixture builders emit exactly those key sets.
  3. Pin the two facts that caused real incidents: position 'type' is the
     STRING 'BUY'/'SELL' on the wire (b34), and every 'time' is a BROKER
     epoch, not UTC (b32/b35).
  4. Pin that the three named consumer test files import the fixtures
     instead of re-hand-rolling payloads.
"""
from __future__ import annotations

import ast
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures_bridge as fb  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / 'scripts' / 'mt5_http_server_v2.py'


def _server_tree() -> ast.Module:
    return ast.parse(SERVER.read_text(encoding='utf-8'))


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f'endpoint function {name}() vanished from the '
                         f'bridge server — the fixtures were pinned against '
                         f'a file that no longer produces this shape')


def _append_dict_keys(fn: ast.FunctionDef) -> tuple:
    """Keys of the dict literal passed to data.append({...}) — the per-item
    payload shape."""
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'append' and node.args
                and isinstance(node.args[0], ast.Dict)):
            return tuple(k.value for k in node.args[0].keys)
    raise AssertionError('no data.append({...}) dict found')


def _jsonify_dict_keys(fn: ast.FunctionDef) -> tuple:
    """Keys of the dict literal in the SUCCESS-path jsonify — the return
    statement at the END of the function body (error paths return
    {ok, error} from the middle; ast.walk's BFS order must not pick those)."""
    last = fn.body[-1]
    assert isinstance(last, ast.Return) and isinstance(last.value, ast.Call) \
        and getattr(last.value.func, 'id', '') == 'jsonify', \
        f'{fn.name}: last statement is not a success jsonify return — the ' \
        f'server response shape moved, re-check the fixtures'
    d = last.value.args[0]
    assert isinstance(d, ast.Dict)
    return tuple(k.value for k in d.keys)


def _rowcomp_dict_keys(fn: ast.FunctionDef) -> tuple:
    """Keys of the dict comprehension item — the OHLC row shape."""
    for node in ast.walk(fn):
        if isinstance(node, ast.ListComp) and isinstance(node.elt, ast.Dict):
            return tuple(k.value for k in node.elt.keys)
    raise AssertionError('no [{...} for r in rates] row found')


def _position_type_expr(fn: ast.FunctionDef):
    """The AST expression assigned to the 'type' key of the position dict."""
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'append' and node.args
                and isinstance(node.args[0], ast.Dict)):
            for k, v in zip(node.args[0].keys, node.args[0].values):
                if k.value == 'type':
                    return v
    raise AssertionError("no 'type' key in the position dict")


class ServerShapeDrift(unittest.TestCase):
    """Fixture field lists vs the ACTUAL server source."""

    def test_positions_item_keys_match_server(self):
        self.assertEqual(_append_dict_keys(_func(_server_tree(),
                                                 'get_positions')),
                         fb.POSITION_FIELDS)

    def test_tick_response_keys_match_server(self):
        self.assertEqual(_jsonify_dict_keys(_func(_server_tree(),
                                                  'get_tick')),
                         fb.TICK_FIELDS)

    def test_account_response_keys_match_server(self):
        self.assertEqual(_jsonify_dict_keys(_func(_server_tree(),
                                                  'get_account')),
                         fb.ACCOUNT_FIELDS)

    def test_deals_item_keys_match_server(self):
        self.assertEqual(_append_dict_keys(_func(_server_tree(),
                                                 'get_history_deals')),
                         fb.DEAL_FIELDS)

    def test_ohlc_row_keys_match_server(self):
        self.assertEqual(_rowcomp_dict_keys(_func(_server_tree(), 'get_ohlc')),
                         fb.RATE_FIELDS)
        self.assertEqual(_rowcomp_dict_keys(_func(_server_tree(),
                                                  'get_rates')),
                         fb.RATE_FIELDS)

    def test_list_envelope_keys_match_server(self):
        tree = _server_tree()
        for fn_name in ('get_positions', 'get_history_deals'):
            keys = set(_jsonify_dict_keys(_func(tree, fn_name)))
            self.assertEqual(keys, set(fb.LIST_ENVELOPE_FIELDS),
                             f'{fn_name} envelope changed')
        # rates carry an extra 'timeframe' field
        self.assertEqual(set(_jsonify_dict_keys(_func(tree, 'get_rates'))),
                         set(fb.LIST_ENVELOPE_FIELDS + ('timeframe',)))


class FixtureEmitsServerShape(unittest.TestCase):
    """The builders themselves must emit exactly the pinned key sets."""

    def test_pos_raw_keys(self):
        self.assertEqual(set(fb.pos_raw()), set(fb.POSITION_FIELDS))

    def test_tick_keys(self):
        self.assertEqual(set(fb.tick_payload()), set(fb.TICK_FIELDS))

    def test_account_keys(self):
        self.assertEqual(set(fb.account_payload()), set(fb.ACCOUNT_FIELDS))

    def test_deal_keys(self):
        self.assertEqual(set(fb.deal_raw()), set(fb.DEAL_FIELDS))

    def test_rate_row_keys(self):
        self.assertEqual(set(fb.rate_row()), set(fb.RATE_FIELDS))

    def test_envelopes(self):
        self.assertEqual(set(fb.positions_payload([fb.pos_raw()])),
                         set(fb.LIST_ENVELOPE_FIELDS))
        self.assertEqual(fb.positions_payload([fb.pos_raw()])['count'], 1)
        self.assertEqual(set(fb.deals_payload()), set(fb.LIST_ENVELOPE_FIELDS))
        self.assertEqual(set(fb.rates_payload()),
                         set(fb.LIST_ENVELOPE_FIELDS + ('timeframe',)))


class WireFactsPinned(unittest.TestCase):
    """The two facts that caused real incidents."""

    def test_position_type_is_a_string_on_the_wire(self):
        """b34: the server ternary emits 'BUY'/'SELL' strings — a fake that
        quietly used ints is what let int('SELL') reach production."""
        expr = _position_type_expr(_func(_server_tree(), 'get_positions'))
        self.assertIsInstance(expr, ast.IfExp)
        consts = {c.value for c in (expr.body, expr.orelse)
                  if isinstance(c, ast.Constant)}
        self.assertEqual(consts, {'BUY', 'SELL'})
        # and the fixture default agrees
        self.assertIsInstance(fb.pos_raw('SELL')['type'], str)
        self.assertEqual(fb.pos_raw('buy')['type'], 'BUY')

    def test_legacy_int_type_shape_is_reproducible(self):
        """The old C:\\Temp\\bridge.py fork sent int type — tests must be
        able to replay THAT shape too (b34's normalizer handles both)."""
        self.assertEqual(fb.pos_raw(type=0)['type'], 0)
        self.assertEqual(fb.pos_raw(type=1)['type'], 1)

    def test_position_time_is_broker_epoch_not_utc(self):
        """b32/b35: 'time' is stamped on the broker clock (UTC+3)."""
        now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        p = fb.pos_raw(age_hours=2.0, now=now)
        self.assertEqual(p['time'],
                         int(now.timestamp()) - 2 * 3600 + fb.BROKER_OFFSET_SEC)

    def test_tick_time_is_broker_epoch(self):
        now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        t = fb.tick_payload(now=now)
        self.assertEqual(t['time'], int(now.timestamp()) + fb.BROKER_OFFSET_SEC)

    def test_consumers_normalize_both_type_shapes(self):
        """The runtime normalizer must accept the fixture shapes verbatim."""
        sys.path.insert(0, str(REPO))
        import hermes_runtime as hr
        self.assertEqual(hr._pos_type(fb.pos_raw('SELL')), 1)
        self.assertEqual(hr._pos_type(fb.pos_raw('BUY')), 0)
        self.assertEqual(hr._pos_type(fb.pos_raw(type=1)), 1)
        self.assertEqual(hr._pos_type(fb.pos_raw(type=0)), 0)
        obj = hr._pos_obj(fb.pos_raw('SELL', ticket=123, entry=4450.0))
        self.assertEqual((obj.ticket, obj.type, obj.price_open, obj.time),
                         (123, 1, 4450.0, fb.pos_raw('SELL', ticket=123,
                          entry=4450.0)['time']))


class ConsumersUseFixtures(unittest.TestCase):
    """The named test files must import the shared fixtures — no more
    private hand-rolled position payloads."""

    def test_named_consumers_import_fixtures(self):
        for name in ('test_integration.py', 'test_daemon_guards.py',
                     'test_runtime_fallback_management.py'):
            src = (Path(__file__).parent / name).read_text(encoding='utf-8')
            self.assertIn('fixtures_bridge', src,
                          f'{name} still hand-rolls bridge payloads')

    def test_no_consumer_redefines_a_position_dict(self):
        """The three consumers must not keep a local dict with the full
        production position key set (that is the fixture's job)."""
        for name in ('test_daemon_guards.py',
                     'test_runtime_fallback_management.py'):
            src = (Path(__file__).parent / name).read_text(encoding='utf-8')
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    keys = {k.value for k in node.keys
                            if isinstance(k, ast.Constant)}
                    self.assertFalse(
                        {'price_open', 'profit', 'time'} <= keys,
                        f'{name} hand-rolls a production position dict — '
                        f'use fixtures_bridge.pos_raw')


if __name__ == '__main__':
    unittest.main()
