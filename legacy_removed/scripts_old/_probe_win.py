import os
import sys
import time
import winrm
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from env_loader import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

s = winrm.Session('192.168.10.51', auth=('Administrator', os.environ['WIN_PASS']),
                  transport='ntlm', server_cert_validation='ignore', read_timeout_sec=120)

def run(c):
    r = s.run_cmd(c)
    return (r.std_out.decode('utf-8', 'replace') + r.std_err.decode('utf-8', 'replace'))[:2500]

# harden the setup:
# 1) MT5Trader boot task runs terminal in session 0 → replace with the interactive autostart
#    put a shortcut in the Administrator's Startup folder (console session, desktop) instead
print(run('powershell -Command "Disable-ScheduledTask -TaskName MT5Trader | Out-Null; '
          "$ws = New-Object -ComObject WScript.Shell; "
          "$lnk = $ws.CreateShortcut('C:\\Users\\Administrator\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\MT5.lnk'); "
          "$lnk.TargetPath = 'C:\\Program Files\\Metatrader 5\\terminal64.exe'; "
          "$lnk.Save(); "
          "Disable-ScheduledTask -TaskName HermesMT5Interactive | Out-Null; "
          "'startup shortcut installed, old tasks disabled'\""))
# 2) re-enable watchdog (it was disabled during surgery)
print(run('powershell -Command "Enable-ScheduledTask -TaskName HermesBridgeWatchdog | Out-Null; Enable-ScheduledTask -TaskName HermesBridge | Out-Null; \'watchdog+bridge enabled\'"'))
