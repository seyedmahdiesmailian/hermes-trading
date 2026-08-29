"""Deploy updated bridge to Windows VM and restart the live bridge.

Audit reality: the LIVE process runs C:\\Temp\\bridge.py (older fork,
'open_price' + int 'type'), not scripts/mt5_http_server_v2.py. This script:
 1. downloads live bridge.py
 2. patches it locally (additive: positions gain price_open+time,
    deals gain entry+order+symbol) — token auth & waitress untouched
 3. pushes patched file back + the evolved v2 for reference
 4. restarts the 5050 listener
"""
import base64
import re
import time
import winrm

s = winrm.Session('192.168.10.51', auth=('Administrator', 'REDACTED_WIN_PASS'),
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


# 1) download live bridge.py
r = s.run_ps("[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\\Temp\\bridge.py'))")
live = base64.b64decode(r.std_out.decode().replace('\r\n', '').replace('\n', ''))
src = live.decode('utf-8')
print("live bridge.py:", len(src), "chars")

# 2) patch positions block: add price_open + time (keep open_price for compat)
pos_old = '''            out.append({
                "ticket": int(p.ticket),
                "type": int(p.type),
                "volume": float(p.volume),
                "open_price": float(p.price_open),
                "profit": float(p.profit),'''
pos_new = '''            out.append({
                "ticket": int(p.ticket),
                "type": int(p.type),
                "volume": float(p.volume),
                "open_price": float(p.price_open),
                "price_open": float(p.price_open),
                "time": int(p.time),
                "profit": float(p.profit),'''
assert pos_old in src, "positions block not found — abort"
src = src.replace(pos_old, pos_new)

# 3) patch deals block: add order/entry keys (symbol already exists)
deal_old = '''        out.append({
            "ticket": int(d.ticket),
            "symbol": d.symbol,
            "type": "BUY" if d.type == 0 else "SELL",
            "volume": float(d.volume), "price": float(d.price),'''
deal_new = '''        out.append({
            "ticket": int(d.ticket),
            "order": int(d.order),
            "entry": int(d.entry),
            "symbol": d.symbol,
            "type": "BUY" if d.type == 0 else "SELL",
            "volume": float(d.volume), "price": float(d.price),'''
assert deal_old in src, "deals block not found — abort"
src = src.replace(deal_old, deal_new)

# sanity: file still compiles as python
compile(src, 'bridge.py', 'exec')
print("patched OK, compiles")

# 4) push patched live + evolved v2 reference copy
push_file('C:\\Temp\\bridge.py', src.encode('utf-8'))
with open('/home/ai/hermes-trading/scripts/mt5_http_server_v2.py', 'rb') as f:
    push_file('C:\\Temp\\mt5_http_server_v2.py', f.read())

# 5) restart the listener on 5050
print(run_ps("$c=Get-NetTCPConnection -LocalPort 5050 -State Listen -EA SilentlyContinue;"
             "if($c){$procId=$c[0].OwningProcess;Stop-Process -Id $procId -Force;'killed '+$procId}else{'no listener'}"))
time.sleep(3)
# relaunch exactly as before: pythonw C:\Temp\bridge.py (env token must be system-level)
print(run_ps("Start-Process -FilePath 'C:\\Program Files\\Python311\\pythonw.exe' "
             "-ArgumentList 'C:\\Temp\\bridge.py' -WorkingDirectory 'C:\\Temp';'launched'"))
time.sleep(8)
print(run_ps("(Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:5050/health -TimeoutSec 15).Content"))
