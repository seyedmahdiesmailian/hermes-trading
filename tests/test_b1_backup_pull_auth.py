"""B1 (review 2026-09-17, report row 4) — the off-box backup pull must be
authenticated.

scripts/offsite_backup.py pushes the daily archive to the Windows VM by
having Windows PULL it over plain LAN HTTP from a throwaway server on this
box. That archive contains .env (EVERY bot token), the Windows VM password
and .git_token. Until this fix the throwaway server was a bare
SimpleHTTPRequestHandler bound to 0.0.0.0 with NO authentication: any LAN
port scanner that hit the ephemeral port during the pull window downloaded
the complete secret set (report §ب/B1: 'هر اسکنر پورت در آن پنجره = مالک
کل secret ها').

The fix: a fresh random token per push, constant-time checked, carried in
the fetch URL (which travels over the NTLM WinRM channel). These tests
exercise the REAL handler against a REAL socket — no mocking of the thing
under test.
"""
from __future__ import annotations

import functools
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))

import offsite_backup as ob  # noqa: E402


def _serve(token: str, fname: str, payload: bytes):
    serve_dir = tempfile.mkdtemp(prefix='hermes_bk_test_')
    (Path(serve_dir) / fname).write_bytes(payload)
    handler = functools.partial(ob._authed_handler(token), directory=serve_dir)
    srv = HTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, serve_dir


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b''


class BackupPullIsAuthenticated(unittest.TestCase):
    PAYLOAD = b'SECRETS: telegram tokens + windows password + git token'

    def setUp(self):
        import secrets
        self.token = secrets.token_urlsafe(32)
        self.srv, self.serve_dir = _serve(self.token, 'hermes_backup_x.tar.gz',
                                          self.PAYLOAD)
        self.base = (f'http://127.0.0.1:{self.srv.server_address[1]}'
                     f'/hermes_backup_x.tar.gz')

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        import shutil
        shutil.rmtree(self.serve_dir, ignore_errors=True)

    def test_no_token_is_refused(self):
        status, body = _get(self.base)
        self.assertEqual(status, 404,
                         'the unauthenticated pull still serves the archive '
                         '— B1 is back')
        self.assertNotIn(self.PAYLOAD[:7], body)

    def test_wrong_token_is_refused(self):
        status, _ = _get(f'{self.base}?token=attacker-guess')
        self.assertEqual(status, 404)

    def test_correct_token_serves_the_archive(self):
        status, body = _get(f'{self.base}?token={self.token}')
        self.assertEqual(status, 200)
        self.assertEqual(body, self.PAYLOAD)

    def test_token_via_header_also_works(self):
        req = urllib.request.Request(self.base,
                                     headers={'X-Backup-Token': self.token})
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.read(), self.PAYLOAD)

    def test_directory_traversal_with_valid_token_stays_in_the_dir(self):
        # the token is not a license to read the whole disk: the handler
        # inherits SimpleHTTPRequestHandler's directory jail
        outside = Path(self.serve_dir).parent / 'hermes_bk_outside.txt'
        outside.write_text('other-tenant-secret', encoding='utf-8')
        try:
            status, _ = _get(f'{self.base.replace("/hermes_backup_x.tar.gz", "")}'
                             f'/../hermes_bk_outside.txt?token={self.token}')
            self.assertIn(status, (301, 404))
        finally:
            outside.unlink(missing_ok=True)


class BackupSourcePinned(unittest.TestCase):
    """The wiring between handler, URL and token (b132 source-pin style)."""

    def test_pull_url_carries_the_token(self):
        src = (REPO / 'scripts' / 'offsite_backup.py').read_text(encoding='utf-8')
        self.assertIn('?token={token}', src,
                      'the Windows-side fetch URL no longer carries the '
                      'one-shot token — the pull would 404 (or worse, the '
                      'token check was removed)')

    def test_comparison_is_constant_time(self):
        src = (REPO / 'scripts' / 'offsite_backup.py').read_text(encoding='utf-8')
        self.assertIn('secrets.compare_digest', src)

    def test_bare_handler_is_not_served(self):
        src = (REPO / 'scripts' / 'offsite_backup.py').read_text(encoding='utf-8')
        self.assertNotIn('functools.partial(SimpleHTTPRequestHandler',
                         src,
                         'a bare unauthenticated SimpleHTTPRequestHandler is '
                         'back on the backup path')

    def test_token_is_generated_not_configured(self):
        # a shared/static token would defeat the one-shot property
        src = (REPO / 'scripts' / 'offsite_backup.py').read_text(encoding='utf-8')
        self.assertIn('secrets.token_urlsafe', src)
        self.assertNotIn("os.getenv('BACKUP_TOKEN'", src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
