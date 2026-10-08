#!/usr/bin/env python3
"""Restart bridge.py on the Windows VM over WinRM.

Credentials and the host come from .env, never from literals in this file:

- The password was previously hardcoded here in plaintext and reached a
  pushed commit. Secrets belong in .env, which is gitignored. NOTE: removing
  it from HEAD does not remove it from git history — the old password must
  be treated as compromised and rotated on the Windows box.
- The host was a hardcoded RFC1918 literal, which breaks the b64 rule that
  every address of our own infrastructure resolves from the environment (a
  rebuild or relocation must not silently keep talking to the old box).

Precedence matches scripts/offsite_backup.py and the deploy scripts (b62):
explicit WIN_HOST override > documented HERMES_WIN_IP > last-known default.
"""
import os
import sys
from pathlib import Path

import urllib3
import winrm

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from env_loader import load_dotenv  # noqa: E402

load_dotenv(ROOT / '.env')

urllib3.disable_warnings()

WIN_HOST = os.getenv('WIN_HOST') or os.getenv('HERMES_WIN_IP', '192.168.10.51')
USER = os.getenv('WIN_USER', 'Administrator')
PASS = os.getenv('WIN_PASS', '')
if not PASS:
    sys.exit("WIN_PASS is not set — restore it from .env (see docs/DEPLOY.md).")

VM = f"https://{WIN_HOST}:5985"

s = winrm.Session(VM, auth=(USER, PASS), transport='ntlm',
                  server_cert_validation='ignore')

# Kill any stale python processes holding the port
ps_kill = r'''
Get-Process python* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Write-Output "Cleaned up old processes"
'''
r = s.run_ps(ps_kill)
print("KILL:", r.std_out.decode('utf-8', errors='replace').strip())

# Start bridge.py
ps_start = r'''
$ErrorActionPreference = 'Stop'
$out = Start-Process python.exe -ArgumentList 'C:\Temp\bridge.py' -WorkingDirectory 'C:\Temp' -WindowStyle Hidden -PassThru -RedirectStandardOutput 'C:\Temp\bridge_out.log' -RedirectStandardError 'C:\Temp\bridge_err.log'
Write-Output "Started PID: $($out.Id)"
Start-Sleep -Seconds 3
if (!$out.HasExited) {
    Write-Output "Status: RUNNING"
} else {
    Write-Output "Status: EXITED ($($out.ExitCode))"
    if (Test-Path 'C:\Temp\bridge_err.log') {
        Get-Content 'C:\Temp\bridge_err.log' -Tail 5
    }
}
'''
r = s.run_ps(ps_start)
print("START:", r.std_out.decode('utf-8', errors='replace').strip())
err = r.std_err.decode('utf-8', errors='replace') if r.std_err else ''
if err.strip():
    print("STDERR:", err[:200])
