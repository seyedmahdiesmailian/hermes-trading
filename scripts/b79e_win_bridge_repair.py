"""b79e — One-shot Windows bridge repair over WinRM.

State found (2026-09-13): VM rebooted at 07:51 local; MT5 is alive in the
CONSOLE session (5176, ~130MB) but a GHOST terminal64.exe was also born in
session 0 (Services). The bridge (pythonw, session 0) keeps calling
mt5.initialize(), which binds to the session-0 ghost instead of the console
terminal -> 'IPC timeout' forever, /health hangs, trading lane blind.

Repair, in order:
  1. kill the session-0 ghost terminal ONLY (console MT5 untouched)
  2. kill pythonw (the bridge + whatever watchdog keeps respawning it)
  3. wait 90s — the HermesBridgeWatchdog scheduled task relaunches the
     bridge; with the ghost gone, initialize() attaches to console MT5
  4. print terminal/pythonw/tasklist + last bridge_err.log lines so the
     operator sees the outcome

Read-mostly: the only kills are the ghost terminal and the bridge process,
both designed to be respawned. NO account, NO files, NO trading changes.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from env_loader import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / '.env')

from winrm.protocol import Protocol  # noqa: E402


def open_shell(p):
    return p.open_shell()


def main():
    p = Protocol(endpoint='http://192.168.10.51:5985/wsman', transport='ntlm',
                 username=os.environ['WIN_USER'], password=os.environ['WIN_PASS'])
    sh = open_shell(p)

    def run(cmd):
        i = p.run_command(sh, 'cmd', ['/c', cmd])
        out, err, code = p.get_command_output(sh, i)
        return out.decode(errors='replace')

    print('BEFORE MT5:\n', run('tasklist /FI "IMAGENAME eq terminal64.exe" /FO TABLE'))
    print('BEFORE pythonw:\n', run('tasklist /FI "IMAGENAME eq pythonw.exe" /FO TABLE'))

    # 1) session-0 ghost terminal only
    print('KILL ghost:', run('taskkill /f /im terminal64.exe /fi "SESSION eq 0"'))
    # 2) bridge processes (watchdog relaunches in <=5 min)
    print('KILL bridge:', run('taskkill /f /im pythonw.exe'))
    p.close_shell(sh)

    print('waiting 95s for watchdog relaunch...')
    time.sleep(95)

    sh = open_shell(p)
    print('AFTER MT5:\n', run('tasklist /FI "IMAGENAME eq terminal64.exe" /FO TABLE'))
    print('AFTER pythonw:\n', run('tasklist /FI "IMAGENAME eq pythonw.exe" /FO TABLE'))
    print('LOG tail:\n', run('powershell -Command "Get-Content C:\\Temp\\bridge_err.log -Tail 8"'))
    p.close_shell(sh)
    p.close_protocol()


if __name__ == '__main__':
    main()
