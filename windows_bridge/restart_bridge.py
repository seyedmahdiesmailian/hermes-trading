#!/usr/bin/env python3
"""Restart bridge.py on Windows VM via WinRM."""
import winrm, urllib3
urllib3.disable_warnings()

VM = 'https://192.168.10.51:5985'
USER = 'Administrator'
PASS = 'Seyed1107@'

s = winrm.Session(VM, auth=(USER, PASS), transport='ntlm', server_cert_validation='ignore')

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