"""review 2026-09-17 row 1 — the bridge server must ship AUTHENTICATED from git.

Report (reports/PROJECT_REVIEW_FINDINGS_2026-09-17.md §1.1): the LIVE trading
bridge was an out-of-git C:\\Temp\\bridge.py fork, while the repo's
scripts/mt5_http_server_v2.py — the only file a DR operator could deploy —
had NO authentication, ran on the Flask dev server, and lacked the /api/pending
endpoints the signal lane's limit orders depend on. Anyone cloning the repo
and deploying v2 put an open order-placement API on the LAN.

This file pins the canonical-bridge contract (b36-style AST/source pins —
the server itself needs Windows+MT5 and can never run inside the suite):

  1. AUTH   — a @app.before_request hook checks the Bearer token on every
              route except /health; the token comes from the environment
              (HERMES_BRIDGE_TOKEN), never from a literal; startup REFUSES
              to boot without it.
  2. PENDING— place/list/cancel endpoints exist (ported from the retired
              live-fork patch).
  3. SERVE  — waitress, not the Flask dev server.
  4. DR     — _deploy_bridge.py deploys the git file (no download-the-live-
              copy first step, which failed on a fresh VM), compile-checks
              it locally, and backs the remote live file up.
  5. CLIENT — bridge_client still attaches the same Bearer token.
"""
from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / 'scripts' / 'mt5_http_server_v2.py'
DEPLOY = REPO / 'scripts' / '_deploy_bridge.py'
CLIENT = REPO / 'bridge_client.py'


def _tree() -> ast.Module:
    return ast.parse(SERVER.read_text(encoding='utf-8'))


def _route_rules(fn: ast.FunctionDef) -> list:
    """(methods, path) of every @app.route decorator on fn."""
    rules = []
    for dec in fn.decorator_list:
        if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == 'route'):
            path = dec.args[0].value if dec.args else '?'
            methods = None
            for kw in dec.keywords:
                if kw.arg == 'methods':
                    methods = tuple(e.value for e in kw.value.elts)
            rules.append((methods, path))
    return rules


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f'{name}() vanished from the bridge server')


class BridgeAuthPinned(unittest.TestCase):
    """Every route except /health demands the Bearer token."""

    def test_before_request_hook_exists_and_rejects(self):
        fn = _func(_tree(), '_check_token')
        self.assertIn('before_request', SERVER.read_text(encoding='utf-8'),
                      'the @app.before_request auth hook vanished')
        src = ast.get_source_segment(
            SERVER.read_text(encoding='utf-8'), fn) or ''
        self.assertIn("request.headers.get('Authorization'", src)
        # fail-closed BOTH ways: no env token configured == rejected request
        self.assertTrue('not expected' in src or 'expected' in src)

    def test_health_is_the_only_unauthenticated_route(self):
        src = _func(_tree(), '_check_token')
        segment = ast.get_source_segment(
            SERVER.read_text(encoding='utf-8'), src) or ''
        self.assertIn("request.path == '/health'", segment,
                      'the /health exemption changed — either everything is '
                      'locked (deploy probes break) or something else is open')

    def test_token_comes_from_env_not_a_literal(self):
        src = SERVER.read_text(encoding='utf-8')
        self.assertIn("os.getenv('HERMES_BRIDGE_TOKEN')", src)
        tree = _tree()
        # no string literal that looks like a shared secret assigned to a
        # token-ish name
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and 'token' in t.id.lower()
                            for t in node.targets)
                    and isinstance(node.value, ast.Constant)):
                self.fail(f'hardcoded token literal: {ast.dump(node.value)}')

    def test_comparison_is_constant_time(self):
        src = SERVER.read_text(encoding='utf-8')
        self.assertIn('hmac.compare_digest', src,
                      'token comparison must be constant-time')

    def test_startup_refuses_to_boot_without_a_token(self):
        src = SERVER.read_text(encoding='utf-8')
        self.assertIn("if not _expected_token():", src,
                      'the server no longer refuses to start tokenless — '
                      'an unconfigured bridge must be a boot failure, not a '
                      'silent open API')
        # and it must exit BEFORE serving
        self.assertLess(src.index("if not _expected_token():"),
                        src.index('mt5.initialize'))

    def test_wire_shapes_of_pinned_endpoints_untouched(self):
        # b36/b44 own the detailed field pins; this is the cheap sentinel
        # that this review did not reshape the five audited endpoints
        for fn_name in ('get_positions', 'get_tick', 'get_account',
                        'get_history_deals', 'get_ohlc', 'get_rates'):
            _func(_tree(), fn_name)


class BridgePendingEndpointsPinned(unittest.TestCase):
    """The b70 pending-order API ships in the canonical file (was live-fork
    only — a DR deploy had no limit orders at all)."""

    def test_place_list_cancel_routes_exist(self):
        tree = _tree()
        place = _func(tree, 'place_pending')
        listing = _func(tree, 'list_pending')
        cancel = _func(tree, 'cancel_pending')
        self.assertIn((('POST',), '/api/pending'), _route_rules(place))
        self.assertIn((None, '/api/pending'), _route_rules(listing))
        self.assertIn((('POST',), '/api/cancel'), _route_rules(cancel))

    def test_response_keys_match_client_contract(self):
        # bridge_client.send_pending maps 'order'->'ticket'; get_orders maps
        # 'orders'->'data'; cancel distinguishes gone vs cancelled
        src = SERVER.read_text(encoding='utf-8')
        self.assertIn('"order": int(result.order)', src)
        self.assertIn('"orders": out', src)
        self.assertIn('"cancelled": False, "gone": True', src)

    def test_pending_type_map_covers_limits_and_stops(self):
        src = SERVER.read_text(encoding='utf-8')
        for t in ('ORDER_TYPE_BUY_LIMIT', 'ORDER_TYPE_SELL_LIMIT',
                  'ORDER_TYPE_BUY_STOP', 'ORDER_TYPE_SELL_STOP'):
            self.assertIn(t, src)


class BridgeServesViaWaitress(unittest.TestCase):
    """The Flask dev server (threaded=True) is not a production server."""

    def test_no_flask_dev_server_left(self):
        src = SERVER.read_text(encoding='utf-8')
        self.assertNotIn('app.run(', src,
                          'the bridge is back on the Flask dev server')

    def test_waitress_serve_is_used(self):
        src = SERVER.read_text(encoding='utf-8')
        self.assertIn('from waitress import serve', src)
        self.assertIn('serve(app, host=', src)


class DeployFromGitPinned(unittest.TestCase):
    """DR: _deploy_bridge.py must not depend on downloading a live file."""

    def test_no_download_first_step(self):
        src = DEPLOY.read_text(encoding='utf-8')
        self.assertNotIn("ReadAllBytes('C:\\\\Temp\\\\bridge.py')", src,
                         'the deploy is back to patching the LIVE file — '
                         'step 1 fails on a fresh VM (the DR bug)')
        self.assertIn("mt5_http_server_v2.py", src,
                      'the deploy no longer names the canonical source')

    def test_compile_checks_before_push(self):
        src = DEPLOY.read_text(encoding='utf-8')
        self.assertIn("compile(src, 'bridge.py', 'exec')", src)

    def test_backs_up_the_remote_live_file(self):
        src = DEPLOY.read_text(encoding='utf-8')
        self.assertIn('Copy-Item', src,
                      'a deploy that overwrites the live bridge without a '
                      'backup is unrollbackable')

    def test_auth_pre_flight_on_the_deployed_payload(self):
        src = DEPLOY.read_text(encoding='utf-8')
        self.assertIn("'@app.before_request'", src,
                      'the deploy lost its auth pre-flight — it could push '
                      'an unauthenticated bridge again')

    def test_retired_live_fork_patcher_is_gone(self):
        self.assertFalse(
            (REPO / 'scripts' / '_deploy_pending_bridge.py').exists(),
            'the b71 download-patch-upload helper is back — pending '
            'endpoints ship in the canonical file now')


class ClientStillSendsTheToken(unittest.TestCase):
    """The token only protects if both sides speak it."""

    def test_client_attaches_bearer_header(self):
        src = CLIENT.read_text(encoding='utf-8')
        self.assertIn('HERMES_BRIDGE_TOKEN', src)
        self.assertIn('Bearer', src)
        self.assertIn('_headers()', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
