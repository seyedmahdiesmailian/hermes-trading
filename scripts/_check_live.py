import sys, os, json, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv  # python-dotenv missing -> local fallback
load_dotenv(Path(__file__).resolve().parent.parent / '.env')
from bridge_client import BridgeClient
c = BridgeClient()  # reads HERMES_BRIDGE_TOKEN from the loaded env
acct = c.get_account()
print('account:', json.dumps(acct, ensure_ascii=False)[:200])
pos = c.get_positions()
d = pos.get('data') if isinstance(pos, dict) else pos
print('open positions:', len(d or []))
for p in (d or []):
    print('  ', p)
h = c.get_history_deals('XAUUSD', 8)
hd = h.get('data') if isinstance(h, dict) else h
print('recent deals:', len(hd or []))
for t in (hd or []):
    tm = datetime.datetime.fromtimestamp(t.get('time', 0))
    print(f"  {tm:%m-%d %H:%M} out={t.get('out')} pnl={t.get('profit')} entry={t.get('price')}")
