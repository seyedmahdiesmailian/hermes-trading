"""b44 verify: is the live Windows bridge patched with position_id?"""
import os
import sys
import winrm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from env_loader import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

s = winrm.Session('192.168.10.51', auth=('Administrator', os.environ['WIN_PASS']),
                  transport='ntlm', server_cert_validation='ignore', read_timeout_sec=150)


def ps(cmd):
    r = s.run_ps(cmd)
    return (r.std_out.decode('utf-8', 'replace') + r.std_err.decode('utf-8', 'replace')).strip()


print('position_id in C:\\Temp\\bridge.py:',
      ps("if (Select-String -Path C:\\Temp\\bridge.py -Pattern 'position_id' -Quiet) {'YES'} else {'NO'}"))
print('bridge.py size/mtime:',
      ps("(Get-Item C:\\Temp\\bridge.py) | ForEach-Object { $_.Length.ToString() + ' bytes, ' + $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm') }"))
print('listener pid on 5050:',
      ps("$c=Get-NetTCPConnection -LocalPort 5050 -State Listen -EA SilentlyContinue; if($c){$c[0].OwningProcess}else{'none'}"))
print('health:', ps("(Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:5050/health -TimeoutSec 20).Content")[:150])
