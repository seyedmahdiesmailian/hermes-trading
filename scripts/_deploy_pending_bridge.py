"""b70 — add /api/pending* endpoints to the LIVE Windows bridge.py.

Idempotent: if the endpoint already exists, it still re-pushes (single
source of truth = PENDING_CODE below) and restarts. Follows the exact
pattern of _deploy_bridge.py (download → patch → compile-check → push →
restart 5050 listener → health).
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

s = winrm.Session(WIN_HOST, auth=(WIN_USER, os.environ['WIN_PASS']),
                  transport='ntlm', server_cert_validation='ignore',
                  read_timeout_sec=120)


def run_ps(c: str) -> str:
    r = s.run_ps(c)
    out = r.std_out.decode('utf-8', 'replace') + r.std_err.decode('utf-8', 'replace')
    if '#< CLIXML' in out:
        out = '\n'.join(l for l in out.splitlines()
                        if not l.startswith('<') and 'CLIXML' not in l)
    return out.strip()


def push_file(remote: str, data: bytes):
    b64 = base64.b64encode(data).decode()
    chunks = [b64[i:i + 2000] for i in range(0, len(b64), 2000)]
    run_ps(f"Remove-Item {remote}.b64 -EA SilentlyContinue; 'ok'")
    for ch in chunks:
        run_ps(f"Add-Content -NoNewline -Path {remote}.b64 -Value '{ch}'")
    print(run_ps(f"$b=[Convert]::FromBase64String((Get-Content {remote}.b64 -Raw));"
                 f"[IO.File]::WriteAllBytes('{remote}',$b);'written '+ (Get-Item '{remote}').Length + ' bytes'"))


PENDING_CODE = '''
# ---- b70: pending (limit) orders for signal entries -------------------
import time as _time
PENDING_TYPES = {2: mt5.ORDER_TYPE_BUY_LIMIT, 3: mt5.ORDER_TYPE_SELL_LIMIT,
                 4: mt5.ORDER_TYPE_BUY_STOP, 5: mt5.ORDER_TYPE_SELL_STOP}


@app.route("/api/pending", methods=["POST"])
def place_pending():
    # NOTE: token auth is enforced globally by the @app.before_request hook;
    # do NOT call _check_token() here (it returns None when auth is OK).
    data = request.get_json(force=True)
    try:
        otype = PENDING_TYPES.get(int(data.get("type", 2)))
        if otype is None:
            return make_json(False, error="type must be 2=BUY_LIMIT 3=SELL_LIMIT")
        symbol = data.get("symbol", "XAUUSD")
        volume = float(data.get("volume", 0.01))
        price = float(data["price"])
        sl = float(data.get("sl", 0) or 0)
        tp = float(data.get("tp", 0) or 0)
        comment = str(data.get("comment", "hermes-sig"))[:27]
        if not mt5.symbol_select(symbol, True):
            return make_json(False, error="symbol select failed: " + symbol)
        req = {"action": mt5.TRADE_ACTION_PENDING, "symbol": symbol,
               "volume": volume, "type": otype, "price": price,
               "sl": sl, "tp": tp, "deviation": 20, "comment": comment,
               "magic": int(data.get("magic", 778899)),
               "type_filling": mt5.ORDER_FILLING_IOC}
        exp = float(data.get("expires_in_hours", 0) or 0)
        if exp > 0:
            req["expiration"] = mt5.ORDER_TIME_SPECIFIED
            req["time_expiration"] = int(_time.time() + exp * 3600)
        res = mt5.order_send(req)
        if res is None:
            return make_json(False, error="order_send None")
        if res.retcode != mt5.TRADE_RETCODE_DONE:
            return make_json(False, error="retcode=%s %s" % (res.retcode, res.comment))
        return make_json(True, order=res.order, price=float(price))
    except Exception as e:
        return make_json(False, error=str(e))


@app.route("/api/pending")
def list_pending():
    try:
        out = []
        for o in (mt5.orders_get() or []):
            out.append({"ticket": int(o.ticket), "type": int(o.type),
                        "symbol": o.symbol, "volume": float(o.volume_current),
                        "price_open": float(o.price_open),
                        "sl": float(o.sl or 0), "tp": float(o.tp or 0),
                        "comment": str(o.comment or ""),
                        "magic": int(o.magic or 0)})
        return make_json(True, orders=out)
    except Exception as e:
        return make_json(False, error=str(e))


@app.route("/api/cancel", methods=["POST"])
def cancel_pending():
    data = request.get_json(force=True)
    try:
        ticket = int(data["ticket"])
        if not mt5.orders_get(ticket=ticket):
            return make_json(True, cancelled=False, gone=True)
        res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            return make_json(False, error="retcode=%s" % (getattr(res, "retcode", "?")))
        return make_json(True, cancelled=True)
    except Exception as e:
        return make_json(False, error=str(e))

'''

# 1) download live bridge.py
r = s.run_ps("[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\\Temp\\bridge.py'))")
src = base64.b64decode(r.std_out.decode().replace('\r\n', '').replace('\n', '')).decode('utf-8')
print("live bridge.py:", len(src), "chars")

if '/api/pending' in src:
    print("pending endpoints already present — refreshing block")
    start = src.index('# ---- b70: pending')
    end = src.index('@app.route("/health")')
    src = src[:start] + PENDING_CODE + '\n' + src[end:]
else:
    anchor = '@app.route("/health")'
    assert anchor in src, "health anchor not found — abort"
    src = src.replace(anchor, PENDING_CODE + '\n' + anchor, 1)

# imports the block needs
if 'import time' not in src:
    src = src.replace('import logging', 'import logging\nimport time', 1)

compile(src, 'bridge.py', 'exec')
print("patched OK, compiles")

# 2) push + restart
push_file('C:\\Temp\\bridge.py', src.encode('utf-8'))
print(run_ps("$c=Get-NetTCPConnection -LocalPort 5050 -State Listen -EA SilentlyContinue;"
             "if($c){$procId=$c[0].OwningProcess;Stop-Process -Id $procId -Force;'killed '+$procId}else{'no listener'}"))
time.sleep(3)
print(run_ps("Start-Process -FilePath 'C:\\Program Files\\Python311\\pythonw.exe' "
             "-ArgumentList 'C:\\Temp\\bridge.py' -WorkingDirectory 'C:\\Temp';'launched'"))
time.sleep(8)
print("health:", run_ps("(Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:5050/health -TimeoutSec 15).Content"))
