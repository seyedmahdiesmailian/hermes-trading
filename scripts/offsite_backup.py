#!/usr/bin/env python3
"""Off-box backup of Hermes trading state (b31, daily 03:15 Tehran).

Without this, a disk loss on 192.168.10.18 destroys .env (tokens), the trade
journal/learning state, and the git repo history — everything. Pushes a
tar.gz of {data/, .env, git bundle of repo} to the Windows VM (192.168.10.51)
over WinRM, keeps the last 14 copies there.

Restore: pull D:\\HermesBackups\\hermes_backup_<ts>.tar.gz, tar xzf,
`git clone hermes_repo.bundle`, point HERMES_DATA_ROOT at data/.
"""
from __future__ import annotations

import base64
import os
import secrets
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = Path(__file__).resolve().parent.parent  # b66: code location, not a literal
sys.path.insert(0, str(BASE))
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv(BASE / '.env')
# WIN_HOST/WIN_USER/WIN_PASS now come from .env (the repo-wide dotenv-fallback
# test caught this script reading os.getenv with no loader at all — it could
# never have run: WIN_PASS was always '').
# b62: WIN_HOST used to be a SECOND name for the SAME fact as the documented
# HERMES_WIN_IP, with its own inline default — a bridge host change moved the
# trading path but the daily backup silently kept pushing to the OLD IP (the
# default won, no error anywhere). Precedence now: explicit WIN_HOST override
# > documented HERMES_WIN_IP > last-known default.
WIN_HOST = os.getenv('WIN_HOST') or os.getenv('HERMES_WIN_IP', '192.168.10.51')
WIN_USER = os.getenv('WIN_USER', 'Administrator')
WIN_PASS = os.getenv('WIN_PASS', '')
REMOTE_DIR = os.getenv('WIN_BACKUP_DIR', 'C:\\HermesBackups')  # D: is FULL (0 bytes free, b31)
KEEP = 14


def log(msg: str):
    print(f"[{datetime.now(timezone.utc).strftime('%F %T')}] {msg}", flush=True)


def build_archive():
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    out = Path(tempfile.gettempdir()) / f'hermes_backup_{ts}.tar.gz'
    # git bundle: full repo history in one file (works without a remote)
    bundle = Path(tempfile.gettempdir()) / f'hermes_repo_{ts}.bundle'
    subprocess.run(['git', '-C', str(BASE), 'bundle', 'create', str(bundle), 'HEAD'],
                   check=True, capture_output=True)
    members = ['./data', './.env']
    if (BASE / '.git_token').exists():
        members.append('./.git_token')  # conditional: missing file must not kill backup
    subprocess.run(
        ['tar', 'czf', str(out),
         '-C', str(BASE),
         '--exclude=./data/xau_plan/plan_history',
         '--exclude=*__pycache__*',
         *members],
        check=True)
    return out, bundle


def _authed_handler(token: str):
    """B1 (2026-09-17, review row 4): a one-shot request handler that
    refuses every request without the per-pull random token.

    The archive this server exposes contains .env (EVERY bot token), the
    Windows VM password and .git_token. The old handler was a bare
    SimpleHTTPRequestHandler on 0.0.0.0 with NO authentication — any LAN
    port scanner that found the ephemeral port during the pull window
    owned the whole secret set. 404 (not 403) on a bad token: no
    existence oracle for a scanner.
    """
    from http.server import SimpleHTTPRequestHandler

    class _TokenHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            supplied = (parse_qs(parsed.query).get('token') or [None])[0] \
                or self.headers.get('X-Backup-Token')
            if not supplied or not secrets.compare_digest(supplied, token):
                self.send_error(404)
                return
            self.path = parsed.path  # strip the token before path math
            super().do_GET()

        def log_message(self, *args):  # keep the cron log quiet
            pass

    return _TokenHandler


def push(remote_path: str, data: bytes, port: int = 0) -> str:
    """b31: Windows PULLS the file over LAN HTTP from a throwaway server here.
    WinRM push is unusable for MB-sized files: envelope limit (413) and the
    32KB PowerShell command-line limit (both hit in testing).

    B1 (2026-09-17): the pull is token-authenticated — a fresh random
    token per push, carried in the URL Windows fetches over the
    already-encrypted WinRM channel, checked constant-time server-side."""
    import winrm
    import threading
    from http.server import HTTPServer
    import functools

    fname = remote_path.rsplit('\\', 1)[-1]
    serve_dir = tempfile.mkdtemp(prefix='hermes_bk_')
    (Path(serve_dir) / fname).write_bytes(data)

    token = secrets.token_urlsafe(32)
    handler = functools.partial(_authed_handler(token), directory=serve_dir)
    srv = HTTPServer(('0.0.0.0', 0), handler)  # ephemeral port
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    port = srv.server_address[1]
    local_ip = os.getenv('HERMES_LAN_IP', '192.168.10.18')

    s = winrm.Session(WIN_HOST, auth=(WIN_USER, WIN_PASS), transport='ntlm',
                      server_cert_validation='ignore', read_timeout_sec=180)

    def run_ps(c: str) -> str:
        r = s.run_ps(c)
        out = r.std_out.decode('utf-8', 'replace') + r.std_err.decode('utf-8', 'replace')
        if '#< CLIXML' in out:
            out = '\n'.join(l for l in out.splitlines()
                            if 'CLIXML' not in l and not l.startswith('<'))
        return out.strip()

    try:
        run_ps(f"New-Item -ItemType Directory -Force -Path '{REMOTE_DIR}' | Out-Null; 'ok'")
        out = run_ps(
            f"Invoke-WebRequest -UseBasicParsing -Uri 'http://{local_ip}:{port}/{fname}?token={token}' "
            f"-OutFile '{remote_path}' -TimeoutSec 120; "
            f"'written ' + (Get-Item '{remote_path}').Length + ' bytes'")
        if 'written' not in out:
            raise RuntimeError(f'pull failed: {out[:200]}')
        return out
    finally:
        srv.shutdown()
        import shutil
        shutil.rmtree(serve_dir, ignore_errors=True)


def prune(s: 'winrm.Session') -> None:
    r = s.run_ps(
        f"$f=Get-ChildItem '{REMOTE_DIR}\\hermes_backup_*.tar.gz' | Sort-Object Name -Descending;"
        f"$f | Select-Object -Skip {KEEP} | Remove-Item -Force; 'kept ' + [Math]::Min({KEEP}, $f.Count)")
    log('prune: ' + r.std_out.decode('utf-8', 'replace').strip())


def main() -> int:
    if not WIN_PASS:
        log('WIN_PASS not set in .env — cannot back up off-box')
        return 2
    archive, bundle = build_archive()
    size = archive.stat().st_size + bundle.stat().st_size
    if size > 60_000_000:
        log(f'archive too big ({size} bytes) — refusing to push over WinRM')
        return 3
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    try:
        out = push(f'{REMOTE_DIR}\\hermes_backup_{ts}.tar.gz', archive.read_bytes())
        log(f'tar: {out}')
        if f'{archive.stat().st_size} bytes' not in out:
            raise RuntimeError(f'tar size mismatch: {out[:120]}')
        out2 = push(f'{REMOTE_DIR}\\hermes_repo_{ts}.bundle', bundle.read_bytes())
        log(f'bundle: {out2}')
        if f'{bundle.stat().st_size} bytes' not in out2:
            raise RuntimeError(f'bundle size mismatch: {out2[:120]}')
        import winrm
        s = winrm.Session(WIN_HOST, auth=(WIN_USER, WIN_PASS), transport='ntlm',
                          server_cert_validation='ignore', read_timeout_sec=120)
        prune(s)
        log('backup OK')
        return 0
    except Exception as e:
        log(f'backup FAILED: {e}')
        # alert via notifier (best effort)
        try:
            sys.path.insert(0, str(BASE))
            from notifier.telegram import send_ops
            send_ops(f'🔴 بک‌آپ آفشور ناموفق: {str(e)[:150]}')
        except Exception:
            pass
        return 1
    finally:
        archive.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
