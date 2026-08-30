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
WIN_HOST = os.getenv('WIN_HOST', '192.168.10.51')
WIN_USER = os.getenv('WIN_USER', 'Administrator')
WIN_PASS = os.getenv('WIN_PASS', '')
REMOTE_DIR = 'D:\\HermesBackups'
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


def push(remote_path: str, data: bytes, chunk: int = 2000000) -> str:
    """WinRM file push via base64 chunks (same pattern as _deploy_bridge)."""
    import winrm
    s = winrm.Session(WIN_HOST, auth=(WIN_USER, WIN_PASS), transport='ntlm',
                      server_cert_validation='ignore', read_timeout_sec=180)

    def run_ps(c: str) -> str:
        r = s.run_ps(c)
        out = r.std_out.decode('utf-8', 'replace') + r.std_err.decode('utf-8', 'replace')
        if '#< CLIXML' in out:
            out = '\n'.join(l for l in out.splitlines()
                            if 'CLIXML' not in l and not l.startswith('<'))
        return out.strip()

    run_ps(f"New-Item -ItemType Directory -Force -Path '{REMOTE_DIR}' | Out-Null; 'ok'")
    b64 = base64.b64encode(data).decode()
    tmp_b64 = remote_path + '.b64'
    run_ps(f"Remove-Item '{tmp_b64}' -EA SilentlyContinue; 'ok'")
    for i in range(0, len(b64), chunk):
        part = b64[i:i + chunk]
        # write raw base64 text pieces to a temp file, join at the end
        run_ps(f"[IO.File]::AppendAllText('{tmp_b64}','{part}')")
    return run_ps(
        "$b=[Convert]::FromBase64String((Get-Content '%s' -Raw));"
        "[IO.File]::WriteAllBytes('%s',$b); Remove-Item '%s';"
        "'written ' + (Get-Item '%s').Length + ' bytes'" % (tmp_b64, remote_path, tmp_b64, remote_path))


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
    ts = archive.stem.replace('hermes_backup_', '')
    try:
        out = push(f'{REMOTE_DIR}\\hermes_backup_{ts}.tar.gz', archive.read_bytes())
        log(f'tar: {out}')
        out2 = push(f'{REMOTE_DIR}\\hermes_repo_{ts}.bundle', bundle.read_bytes())
        log(f'bundle: {out2}')
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
            from notifier.telegram import send_message
            send_message(f'🔴 بک‌آپ آفشور ناموفق: {str(e)[:150]}')
        except Exception:
            pass
        return 1
    finally:
        archive.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
