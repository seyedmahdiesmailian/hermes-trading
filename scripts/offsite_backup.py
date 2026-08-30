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
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/home/ai/hermes-trading')
sys.path.insert(0, str(BASE))
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing → local fallback
load_dotenv(BASE / '.env')
# WIN_HOST/WIN_USER/WIN_PASS now come from .env (the repo-wide dotenv-fallback
# test caught this script reading os.getenv with no loader at all — it could
# never have run: WIN_PASS was always '').
WIN_HOST = os.getenv('WIN_HOST', '192.168.10.51')
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
    subprocess.run(
        ['tar', 'czf', str(out),
         '-C', str(BASE),
         '--exclude=./data/xau_plan/plan_history',
         '--exclude=*__pycache__*',
         './data', './.env'],
        check=True)
    return out, bundle


def push(remote_path: str, data: bytes, port: int = 0) -> str:
    """b31: Windows PULLS the file over LAN HTTP from a throwaway server here.
    WinRM push is unusable for MB-sized files: envelope limit (413) and the
    32KB PowerShell command-line limit (both hit in testing)."""
    import winrm
    import threading
    from http.server import SimpleHTTPRequestHandler, HTTPServer
    import functools

    fname = remote_path.rsplit('\\', 1)[-1]
    serve_dir = tempfile.mkdtemp(prefix='hermes_bk_')
    (Path(serve_dir) / fname).write_bytes(data)

    handler = functools.partial(SimpleHTTPRequestHandler, directory=serve_dir)
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
            f"Invoke-WebRequest -UseBasicParsing -Uri 'http://{local_ip}:{port}/{fname}' "
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
            from notifier.telegram import send_telegram
            send_telegram(f'🔴 بک‌آپ آفشور ناموفق: {str(e)[:150]}')
        except Exception:
            pass
        return 1
    finally:
        archive.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
