"""Re-parse today's raw signal texts with the FIXED parser, then replay them
against the real M5 path. This answers: were the rejections right or wrong?"""
import json
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
from engines.signal_parser import parse_signal

TEHRAN = timezone(timedelta(hours=3, minutes=30))

b = BridgeClient()
rows = b.get_rates('XAUUSD', 'M5', 600)['data']
path = sorted(
    (datetime.fromtimestamp(int(x['time']), tz=timezone.utc),
     float(x['open']), float(x['high']), float(x['low']), float(x['close']))
    for x in rows)

d = json.load(open(os.path.join(_ROOT, 'data/signals/signals_log.json')))
items = d if isinstance(d, list) else d.get('signals', d.get('items', []))

print('day range: low %.2f  high %.2f' % (min(x[3] for x in path), max(x[2] for x in path)))
for s in items:
    ts = s.get('timestamp') or ''
    if ts < '2026-09-04':
        continue
    t0 = datetime.fromisoformat(ts)
    before = [x for x in path if x[0] <= t0]
    if not before:
        continue
    mkt = before[-1][4]
    win = [x for x in path if x[0] <= t0]
    lo = min(x[3] for x in win[-24:]); hi = max(x[2] for x in win[-24:])
    old = s.get('parsed') or {}
    sig = parse_signal(s.get('raw_text') or '', current_price=mkt, price_band=(lo, hi))
    if not sig.side or not sig.entry:
        continue
    dec = s.get('decision') or {}
    print('=== %s  %s' % (t0.astimezone(TEHRAN).strftime('%H:%M'),
                          (s.get('raw_text') or '').replace('\n', ' / ')[:48]))
    print('    OLD parse: entry=%s sl=%s tp=%s   |   FIXED: entry=%s legs=%s sl=%s tp=%s rr=%s'
          % (old.get('entry'), old.get('sl'), old.get('tp'), sig.entry, sig.entries,
             sig.sl, sig.tp, round(sig.computed_rr, 2)))
    print('    verdict=%s' % dec.get('reasons'))
    fwd = [x for x in path if x[0] >= t0]
    for leg in ([sig.entry] + [e for e in (sig.entries or []) if abs(e - sig.entry) > 0.01]):
        # "price comes DOWN to us" = leg below market, for either side.
        # BUY below mkt / SELL below mkt are both limit-style waits for a
        # pullback; the opposite is a stop (breakout).
        want_low = leg < mkt
        fill = next((x for x in fwd
                     if ((x[3] <= leg) if want_low else (x[2] >= leg))), None)
        if fill is None:
            print('      leg %.2f (%s): never reached' % (leg, 'limit' if want_low else 'stop'))
            continue
        after = fwd[fwd.index(fill):]
        out = None
        for x in after:
            if sig.side == 'BUY':
                if sig.sl and x[3] <= sig.sl: out = ('SL', sig.sl); break
                if sig.tp and x[2] >= sig.tp: out = ('TP1', sig.tp); break
            else:
                if sig.sl and x[2] >= sig.sl: out = ('SL', sig.sl); break
                if sig.tp and x[3] <= sig.tp: out = ('TP1', sig.tp); break
        if sig.side == 'BUY':
            mfe = max(x[2] for x in after) - leg; mae = leg - min(x[3] for x in after)
        else:
            mfe = leg - min(x[3] for x in after); mae = max(x[2] for x in after) - leg
        if out:
            pnl = (out[1] - leg) if sig.side == 'BUY' else (leg - out[1])
            res = '%s %+.0f pips' % (out[0], pnl * 10)
        else:
            last = after[-1][4]
            pnl = (last - leg) if sig.side == 'BUY' else (leg - last)
            res = 'open %+.0f pips' % (pnl * 10)
        print('      leg %.2f (%s) filled %s → %s | best %+.0f pips, worst -%.0f pips'
              % (leg, 'limit' if want_low else 'stop',
                 fill[0].astimezone(TEHRAN).strftime('%H:%M'), res, mfe * 10, mae * 10))
