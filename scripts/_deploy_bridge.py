"""Deploy the CANONICAL bridge (git) to the Windows VM and restart it.

review-fix 2026-09-17 (report row 1): this script used to start by
DOWNLOADING the live C:\\Temp\\bridge.py and patching it — so after a
Windows VM loss (the exact DR scenario docs/DEPLOY.md step 5 exists for)
step 1 failed on a fresh box, and the only deployable source left in the
repo was mt5_http_server_v2.py WITHOUT auth. The live bridge was an
out-of-git fork maintained by string patches; drift between it and the
repo copy was invisible (only v2 was AST-checked by the tests).

Now the flow is one-directional, git → Windows:

 1. read scripts/mt5_http_server_v2.py from THIS checkout (the canonical,
    authenticated, waitress-served source — pending endpoints included,
    so _deploy_pending_bridge.py is retired)
 2. compile-check it locally (a broken deploy must fail HERE, not on the
    trading box)
 3. back up the remote live file to C:\\Temp\\bridge.py.bak-<ts>
 4. push the canonical file to C:\\Temp\\bridge.py
 5. restart the 5050 listener (pythonw, same as before)
 6. health check (the /health endpoint is intentionally unauthenticated;
    trading endpoints need HERMES_BRIDGE_TOKEN as a SYSTEM env var on the
    Windows box — the server refuses to boot without it)

b64 note kept: host resolution is WIN_HOST > HERMES_WIN_IP > last-known
default, never a hardcoded IP. The 127.0.0.1 health check stays literal ON
PURPOSE: it runs inside the Windows VM where loopback is the bridge itself.
"""
import base64
import os
import sys
import time
import winrm
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from env_loader import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

WIN_HOST = (os.getenv('WIN_HOST')
            or os.getenv('HERMES_WIN_IP', '192.168.10.51'))
WIN_USER = os.getenv('WIN_USER', 'Administrator')

CANONICAL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'mt5_http_server_v2.py')
REMOTE_PATH = 'C:\\Temp\\bridge.py'

s = winrm.Session(WIN_HOST, auth=(WIN_USER, os.environ['WIN_PASS']),
                  transport='ntlm', server_cert_validation='ignore', read_timeout_sec=120)


def run_ps(c: str) -> str:
    r = s.run_ps(c)
    out = r.std_out.decode('utf-8', 'replace') + r.std_err.decode('utf-8', 'replace')
    if '#< CLIXML' in out:
        out = '\n'.join(l for l in out.splitlines() if not l.startswith('<') and 'CLIXML' not in l)
    return out.strip()


def push_file(remote: str, data: bytes):
    b64 = base64.b64encode(data).decode()
    chunks = [b64[i:i + 2000] for i in range(0, len(b64), 2000)]
    run_ps(f"Remove-Item {remote}.b64 -EA SilentlyContinue; 'ok'")
    for ch in chunks:
        run_ps(f"Add-Content -NoNewline -Path {remote}.b64 -Value '{ch}'")
    print(run_ps(f"$b=[Convert]::FromBase64String((Get-Content {remote}.b64 -Raw));"
                 f"[IO.File]::WriteAllBytes('{remote}',$b);'written '+ (Get-Item '{remote}').Length + ' bytes'"))


# 1) canonical source from THIS checkout
with open(CANONICAL, 'rb') as f:
    payload = f.read()
src = payload.decode('utf-8')
print(f"canonical {os.path.relpath(CANONICAL)}: {len(src)} chars")

# hard pre-flight: the file we are about to make LIVE must carry auth.
# If this ever fails, someone is deploying a non-canonical fork again.
for required in ('@app.before_request', 'HERMES_BRIDGE_TOKEN', 'waitress'):
    assert required in src, f"canonical bridge lost '{required}' — aborting deploy"

# 2) compile check HERE, not on the trading box
compile(src, 'bridge.py', 'exec')
print("compiles OK")

# 3) back up the live file (first deploy on a fresh VM: nothing to back up)
print(run_ps(f"$ts=Get-Date -Format yyyyMMdd_HHmmss; "
             f"if (Test-Path '{REMOTE_PATH}') {{ Copy-Item '{REMOTE_PATH}' "
             f"'{REMOTE_PATH}.bak-'+$ts; 'backed up -> bridge.py.bak-'+$ts }} "
             f"else {{ 'fresh box: no previous bridge' }}"))

# 4) push
push_file(REMOTE_PATH, payload)

# 5) restart the listener on 5050
print(run_ps("$c=Get-NetTCPConnection -LocalPort 5050 -State Listen -EA SilentlyContinue;"
             "if($c){$procId=$c[0].OwningProcess;Stop-Process -Id $procId -Force;'killed '+$procId}else{'no listener'}"))
time.sleep(3)
# relaunch exactly as before: pythonw C:\Temp\bridge.py (token must be system-level)
print(run_ps("Start-Process -FilePath 'C:\\Program Files\\Python311\\pythonw.exe' "
             "-ArgumentList 'C:\\Temp\\bridge.py' -WorkingDirectory 'C:\\Temp';'launched'"))
time.sleep(8)

# 6) health — open by design (no account data); trading endpoints need the
# token. A 000/empty answer here means the server refused to boot: check
# that HERMES_BRIDGE_TOKEN exists as a SYSTEM env var on the Windows box.
print("health:", run_ps("(Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:5050/health -TimeoutSec 15).Content"))
