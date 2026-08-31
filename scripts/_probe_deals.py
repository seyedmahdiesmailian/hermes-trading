import sys, datetime
sys.path.insert(0, '.')
from pathlib import Path
from env_loader import load_dotenv
load_dotenv(Path('.env'))
from bridge_client import BridgeClient

b = BridgeClient()
r = b.get_history_deals('', 30)   # no symbol filter
d = (r or {}).get('data', []) or []
print('all-symbol deals 30d:', len(d))
for x in sorted(d, key=lambda v: v['time']):
    t = datetime.datetime.utcfromtimestamp(x['time']).strftime('%m-%d %H:%M')
    print(t, x['symbol'], 'ticket=', x['ticket'], 'order=', x.get('order'),
          'entry=', x['entry'], x['type'], 'vol=', x['volume'],
          'profit=', x['profit'], repr(x['comment']))
