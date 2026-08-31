"""b44: add `position_id` to the /api/history/deals payload on the LIVE bridge.

Why: partial closes produce OUT deals whose `order` is the deal's own id, so
the Linux side cannot group all deals of one position by `order`. MT5's
Deal.position_id is the position ticket — with it, realized PnL per trade is
computable (the close report was showing the FLOATING pnl of the last
remaining lot slice instead of the real trade result).

Additive only: token auth, waitress, every other field untouched.
"""
import base64
import os
import sys
import time
import winrm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from env_loader import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

s = winrm.Session('192.168.10.51', auth=('Administrator', os.environ['WIN_PASS']),
                  transport='ntlm', server_cert_validation='ignore', read_timeout_sec=180)


def run_ps(c: str) -> str:
    r = s.run_ps(c)
    out = r.std_out.decode('utf-8', 'replace') + r.std_err.decode('utf-8', 'replace')
    if '#< CLIXML' in out:
        out = '\n'.join(l for l in out.splitlines() if not l.startswith('<') and 'CLIXML' not in l)
    return out.strip()


r = s.run_ps("[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\\Temp\\bridge.py'))")
src = base64.b64decode(r.std_out.decode().replace('\r\n', '').replace('\n', '')).decode('utf-8')
print('live bridge.py:', len(src), 'chars')

if '"position_id"' in src:
    print('already patched')
    sys.exit(0)

old = '''            "ticket": int(d.ticket),
            "order": int(d.order),'''
new = '''            "ticket": int(d.ticket),
            "order": int(d.order),
            "position_id": int(getattr(d, "position_id", 0) or 0),'''
assert old in src, 'deals block not found — abort'
src = src.replace(old, new, 1)
compile(src, 'bridge.py', 'exec')
print('patched OK, compiles')

b64 = base64.b64encode(src.encode('utf-8')).decode()
chunks = [b64[i:i + 2000] for i in range(0, len(b64), 2000)]
run_ps("Remove-Item C:\\Temp\\bridge.py.b64 -EA SilentlyContinue; 'ok'")
for ch in chunks:
    run_ps(f"Add-Content -NoNewline -Path C:\\Temp\\bridge.py.b64 -Value '{ch}'")
print(run_ps("$b=[Convert]::FromBase64String((Get-Content C:\\Temp\\bridge.py.b64 -Raw));"
             "[IO.File]::WriteAllBytes('C:\\Temp\\bridge.py',$b);'written '+ (Get-Item 'C:\\Temp\\bridge.py').Length + ' bytes'"))

print(run_ps("$c=Get-NetTCPConnection -LocalPort 5050 -State Listen -EA SilentlyContinue;"
             "if($c){$procId=$c[0].OwningProcess;Stop-Process -Id $procId -Force;'killed '+$procId}else{'no listener'}"))
time.sleep(3)
print(run_ps("Start-Process -FilePath 'C:\\Program Files\\Python311\\pythonw.exe' "
             "-ArgumentList 'C:\\Temp\\bridge.py' -WorkingDirectory 'C:\\Temp';'launched'"))
time.sleep(10)
print(run_ps("(Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:5050/health -TimeoutSec 20).Content"))
