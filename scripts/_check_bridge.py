import os, urllib.request, json
from dotenv import load_dotenv; load_dotenv('/home/ai/hermes-trading/.env')
H = {"Authorization": f"Bearer {os.getenv('HERMES_BRIDGE_TOKEN', '')}"}
def get(ep):
    req = urllib.request.Request(f"http://192.168.10.51:5050{ep}", headers=H)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)
acc = get("/api/account")
tick = get("/api/tick/XAUUSD")
pos = get("/api/positions?symbol=XAUUSD")
print("balance:", acc.get("balance"), "| equity:", acc.get("equity"))
print("tick:", tick.get("bid"), tick.get("ask"))
print("open positions:", len(pos.get("data", pos.get("positions", []))))
