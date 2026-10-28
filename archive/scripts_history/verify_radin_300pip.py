"""Verify the channel's '300 pip' claim on the RADIN SELL ladder — correct
MT5 fill semantics this time.

Signal (Tehran 16:42 / 13:12 UTC): '390 و 400 فروش / استاپ 410 / تی پی 380، 70، 60'
Parsed: SELL legs 4390 & 4400, SL 4410, targets 4380 / 4370 / 4360.
Market at receipt: ~4470.

Fill rules:
  SELL leg BELOW market  = sell STOP  → fills when low  <= leg
  SELL leg ABOVE market  = sell LIMIT → fills when high >= leg
  BUY  leg ABOVE market  = buy  STOP  → fills when high >= leg
  BUY  leg BELOW market  = buy  LIMIT → fills when low  <= leg
The outcome walk starts on the candle AFTER the fill candle, because the
filling candle also contains the pre-entry extreme (it would fake an SL).
"""
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

TEHRAN = timezone(timedelta(hours=3, minutes=30))
b = BridgeClient()
rows = b.get_rates('XAUUSD', 'M5', 600)['data']
path = sorted((datetime.fromtimestamp(int(x['time']), tz=timezone.utc),
               float(x['high']), float(x['low'])) for x in rows)


def fill_candle(fwd, side, leg, mkt):
    """Return (candle, kind) for the first touch of `leg`, or (None, kind)."""
    if side == 'SELL':
        if leg < mkt:
            return next((x for x in fwd if x[2] <= leg), None), 'STOP (price falls to it)'
        return next((x for x in fwd if x[1] >= leg), None), 'LIMIT (price rises to it)'
    if leg > mkt:
        return next((x for x in fwd if x[1] >= leg), None), 'STOP (price rises to it)'
    return next((x for x in fwd if x[2] <= leg), None), 'LIMIT (price falls to it)'


def walk(side, leg, sl, tps, after):
    """First-touch resolution: SL vs each TP, from the candle after fill."""
    def hits_sl(x):
        return x[1] >= sl if side == 'SELL' else x[2] <= sl

    def hits_tp(x, tp):
        return x[2] <= tp if side == 'SELL' else x[1] >= tp

    first_sl = next((x for x in after if hits_sl(x)), None)
    rows_out = []
    for i, tp in enumerate(tps, 1):
        touch = next((x for x in after if hits_tp(x, tp)), None)
        pips = int(abs(tp - leg) * 10)
        if touch is None:
            rows_out.append('TP%d %.2f = %d pips: never reached' % (i, tp, pips))
        elif first_sl and touch[0] > first_sl[0]:
            rows_out.append('TP%d %.2f = %d pips: touched %s BUT after SL → unreachable'
                            % (i, tp, pips, touch[0].astimezone(TEHRAN).strftime('%H:%M')))
        else:
            rows_out.append('TP%d %.2f = %d pips: TOUCHED %s OK'
                            % (i, tp, pips, touch[0].astimezone(TEHRAN).strftime('%H:%M')))
    return first_sl, rows_out


t0 = datetime(2026, 9, 4, 13, 12, tzinfo=timezone.utc)
fwd = [x for x in path if x[0] >= t0]
mkt = [x for x in path if x[0] <= t0][-1][2]
print('RADIN SELL ladder — signal 16:42 Tehran, market %.2f' % mkt)
print('after signal: high %.2f  low %.2f' % (max(x[1] for x in fwd), min(x[2] for x in fwd)))
for leg in (4390.0, 4400.0):
    fill, kind = fill_candle(fwd, 'SELL', leg, mkt)
    print('\nSELL %.2f  [%s]' % (leg, kind))
    if fill is None:
        print('   never filled')
        continue
    print('   filled %s Tehran' % fill[0].astimezone(TEHRAN).strftime('%H:%M'))
    first_sl, lines = walk('SELL', leg, 4410.0, [4380.0, 4370.0, 4360.0],
                           fwd[fwd.index(fill) + 1:])
    for ln in lines:
        print('   ' + ln)
    print('   SL 4410: %s' % (('hit %s → -200 pips' % first_sl[0].astimezone(TEHRAN).strftime('%H:%M'))
                              if first_sl else 'never hit'))

# The other RADIN ladder from 15:08 Tehran (BUY)
print('\n' + '=' * 60)
t1 = datetime(2026, 9, 4, 11, 38, tzinfo=timezone.utc)
fwd1 = [x for x in path if x[0] >= t1]
mkt1 = [x for x in path if x[0] <= t1][-1][2]
print('RADIN BUY ladder — signal 15:08 Tehran, market %.2f' % mkt1)
for leg in (4467.0, 4457.0):
    fill, kind = fill_candle(fwd1, 'BUY', leg, mkt1)
    print('\nBUY %.2f  [%s]' % (leg, kind))
    if fill is None:
        print('   never filled'); continue
    print('   filled %s' % fill[0].astimezone(TEHRAN).strftime('%H:%M'))
    first_sl, lines = walk('BUY', leg, 4447.0, [4477.0, 4487.0, 4497.0],
                           fwd1[fwd1.index(fill) + 1:])
    for ln in lines:
        print('   ' + ln)
    print('   SL 4447: %s' % (('hit %s → -200 pips' % first_sl[0].astimezone(TEHRAN).strftime('%H:%M'))
                              if first_sl else 'never hit'))
