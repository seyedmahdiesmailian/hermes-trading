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
h = c.get_history_deals('XAUUSD', 60)
hd = h.get('data') if isinstance(h, dict) else h
deals = [t for t in (hd or []) if t.get('profit') is not None]
# group by ticket
by = {}
for t in deals:
    tk = t.get('ticket') or t.get('order')
    by.setdefault(tk, []).append(t)
day = {}
tot = 0.0
for tk, legs in by.items():
    pnl = sum(l.get('profit', 0) or 0 for l in legs)
    tm = datetime.datetime.utcfromtimestamp(legs[0].get('time', 0)) + datetime.timedelta(hours=3, minutes=30)
    if tm >= datetime.datetime(2026, 9, 2):
        day[tk] = (tm, legs[0].get('type') or legs[0].get('direction'), pnl, legs[0].get('volume'))
        tot += pnl
print('=== trades since Sep 2 (Tehran) ===')
for tk, (tm, side, pnl, vol) in sorted(day.items(), key=lambda x: x[1][0]):
    print(f'#{tk} {tm:%m-%d %H:%M} {side} {vol} -> {pnl:+.2f}$')
print(f'NET today = {tot:+.2f}$   count={len(day)}   wins={sum(1 for v in day.values() if v[2]>0)}')
