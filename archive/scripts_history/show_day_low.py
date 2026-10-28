"""When did the day's extremes print? Guards against reading a stale window."""
import os
import sys
from datetime import datetime, timezone, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
try:
    from dotenv import load_dotenv
except ImportError:
    from env_loader import load_dotenv
load_dotenv(os.path.join(_ROOT, '.env'))

from bridge_client import BridgeClient

TEH = timezone(timedelta(hours=3, minutes=30))
rows = BridgeClient().get_rates('XAUUSD', 'M5', 600)['data']
bars = [(datetime.fromtimestamp(int(r['time']), tz=timezone.utc),
         float(r['high']), float(r['low'])) for r in rows]
today = [b for b in bars if b[0].date() == datetime.now(timezone.utc).date()]
hi = max(today, key=lambda b: b[1])
lo = min(today, key=lambda b: b[2])
print('today bars:', len(today))
print('HIGH', f"{hi[1]:.2f}", hi[0].astimezone(TEH).strftime('%H:%M Tehran'))
print('LOW ', f"{lo[2]:.2f}", lo[0].astimezone(TEH).strftime('%H:%M Tehran'))
for rung in (4360.0, 4350.0, 4323.4):
    hit = next((b for b in today if b[2] <= rung), None)
    print(f'  touched {rung}:',
          hit[0].astimezone(TEH).strftime('%H:%M') if hit else 'never')
