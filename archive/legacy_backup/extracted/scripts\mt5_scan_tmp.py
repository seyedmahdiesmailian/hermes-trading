import json
import MetaTrader5 as mt5

symbols = ['XAUUSD','EURUSD','GBPUSD','USDJPY','BTCUSD','ETHUSD','SPXUSD','DJIUSD','DAXEUR']
timeframes = {'M15': mt5.TIMEFRAME_M15, 'H1': mt5.TIMEFRAME_H1, 'H4': mt5.TIMEFRAME_H4, 'D1': mt5.TIMEFRAME_D1}

def ensure_symbol(sym):
    info = mt5.symbol_info(sym)
    if info is None:
        return None
    if not info.visible:
        mt5.symbol_select(sym, True)
        info = mt5.symbol_info(sym)
    return info

def rates(sym, tf, n):
    return mt5.copy_rates_from_pos(sym, tf, 0, n)

def atr(arr, period=14):
    if arr is None or len(arr) < period + 1:
        return None
    trs = []
    prev = arr[0]['close']
    for i in range(1, len(arr)):
        h, l = arr[i]['high'], arr[i]['low']
        trs.append(max(h - l, abs(h - prev), abs(l - prev)))
        prev = arr[i]['close']
    return sum(trs[-period:]) / period if len(trs) >= period else None

def swing_levels(arr, lookback):
    seg = arr[-lookback:]
    return max(x['high'] for x in seg), min(x['low'] for x in seg)

def trend_score(arr):
    closes = [x['close'] for x in arr]
    if len(closes) < 50:
        return 0
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50
    last = closes[-1]
    if last > sma20 > sma50:
        return 1
    if last < sma20 < sma50:
        return -1
    return 0

def momentum(arr):
    closes = [x['close'] for x in arr]
    if len(closes) < 11:
        return 0
    ret5 = closes[-1] - closes[-6]
    ret10 = closes[-1] - closes[-11]
    if ret5 > 0 and ret10 > 0:
        return 1
    if ret5 < 0 and ret10 < 0:
        return -1
    return 0

def analyze(sym):
    info = ensure_symbol(sym)
    if info is None:
        return {'symbol': sym, 'available': False, 'reason': 'no_symbol'}
    data = {k: rates(sym, tf, 120) for k, tf in timeframes.items()}
    if any(v is None or len(v) < 80 for v in data.values()):
        return {'symbol': sym, 'available': False, 'reason': 'insufficient_rates'}
    tick = mt5.symbol_info_tick(sym)
    h4, h1, m15, d1 = data['H4'], data['H1'], data['M15'], data['D1']
    h4_tr = trend_score(h4)
    h1_tr = trend_score(h1)
    m15_mom = momentum(m15)
    h1_atr = atr(h1, 14)
    d1_atr = atr(d1, 14)
    hi20, lo20 = swing_levels(h1, 20)
    hi10, lo10 = swing_levels(h1, 10)
    last = h1[-1]['close']
    prev = h1[-2]['close']
    pd = (last - lo20) / max(hi20 - lo20, 1e-9)
    lastbar = h1[-1]
    sweep_high = lastbar['high'] > hi10 and lastbar['close'] < hi10
    sweep_low = lastbar['low'] < lo10 and lastbar['close'] > lo10
    bull_break = last > hi10 and prev <= hi10
    bear_break = last < lo10 and prev >= lo10
    pullback_q = abs(last - (sum(x['close'] for x in h1[-20:]) / 20)) / max(h1_atr or 1e-9, 1e-9)
    long_pts = short_pts = 0
    long_r, short_r = [], []
    if h4_tr > 0:
        long_pts += 2; long_r.append('HTF up')
    if h4_tr < 0:
        short_pts += 2; short_r.append('HTF down')
    if h1_tr > 0:
        long_pts += 2; long_r.append('LTF up')
    if h1_tr < 0:
        short_pts += 2; short_r.append('LTF down')
    if m15_mom > 0:
        long_pts += 1; long_r.append('mom+')
    if m15_mom < 0:
        short_pts += 1; short_r.append('mom-')
    if sweep_low:
        long_pts += 2; long_r.append('sell sweep')
    if sweep_high:
        short_pts += 2; short_r.append('buy sweep')
    if bull_break:
        long_pts += 1; long_r.append('breakout')
    if bear_break:
        short_pts += 1; short_r.append('breakdown')
    if pd < 0.35:
        long_pts += 1; long_r.append('discount')
    if pd > 0.65:
        short_pts += 1; short_r.append('premium')
    if pullback_q > 1.8:
        if long_pts > short_pts:
            long_pts -= 1; long_r.append('stretched')
        elif short_pts > long_pts:
            short_pts -= 1; short_r.append('stretched')
    direction = 'BUY' if long_pts > short_pts else 'SELL' if short_pts > long_pts else 'NONE'
    score = abs(long_pts - short_pts)
    rr = None
    sl_pts = None
    tp_pts = None
    if direction != 'NONE' and h1_atr and info.point:
        stop_dist = 1.2 * h1_atr
        target_dist = 2.2 * h1_atr
        rr = target_dist / stop_dist
        sl_pts = int(round(stop_dist / info.point))
        tp_pts = int(round(target_dist / info.point))
    return {
        'symbol': sym,
        'available': True,
        'spread': (tick.ask - tick.bid) if tick else None,
        'point': info.point,
        'volume_min': info.volume_min,
        'volume_step': info.volume_step,
        'h4_trend': h4_tr,
        'h1_trend': h1_tr,
        'm15_momentum': m15_mom,
        'pd_location': round(pd, 3),
        'sweep_high': sweep_high,
        'sweep_low': sweep_low,
        'bull_break': bull_break,
        'bear_break': bear_break,
        'pullback_quality_atr': round(pullback_q, 2),
        'direction': direction,
        'score': score,
        'reasons': (long_r if direction == 'BUY' else short_r if direction == 'SELL' else [])[:5],
        'rr_est': round(rr, 2) if rr else None,
        'sl_points': sl_pts,
        'tp_points': tp_pts,
        'atr_h1': h1_atr,
        'atr_d1': d1_atr,
        'bid': tick.bid if tick else None,
        'ask': tick.ask if tick else None,
    }

if not mt5.initialize():
    print(json.dumps({'ok': False, 'last_error': mt5.last_error()}, ensure_ascii=False))
    raise SystemExit(1)
try:
    res = [analyze(s) for s in symbols]
    idx = {r['symbol']: r for r in res if r.get('available')}
    risk_on = sum(1 for s in ['SPXUSD', 'DJIUSD', 'DAXEUR', 'BTCUSD', 'ETHUSD'] if idx.get(s, {}).get('direction') == 'BUY')
    risk_off = sum(1 for s in ['SPXUSD', 'DJIUSD', 'DAXEUR', 'BTCUSD', 'ETHUSD'] if idx.get(s, {}).get('direction') == 'SELL')
    usd_strength = 0
    if idx.get('EURUSD', {}).get('direction') == 'SELL':
        usd_strength += 1
    if idx.get('GBPUSD', {}).get('direction') == 'SELL':
        usd_strength += 1
    if idx.get('USDJPY', {}).get('direction') == 'BUY':
        usd_strength += 1
    for r in res:
        if not r.get('available'):
            continue
        bonus = 0
        if r['symbol'] in ['SPXUSD', 'DJIUSD', 'DAXEUR', 'BTCUSD', 'ETHUSD']:
            if (risk_on >= 3 and r['direction'] == 'BUY') or (risk_off >= 3 and r['direction'] == 'SELL'):
                bonus += 1
        if r['symbol'] == 'XAUUSD':
            if usd_strength >= 2 and r['direction'] == 'SELL':
                bonus += 1
            if usd_strength == 0 and r['direction'] == 'BUY':
                bonus += 1
        if r['symbol'] in ['EURUSD', 'GBPUSD'] and usd_strength >= 2 and r['direction'] == 'SELL':
            bonus += 1
        if r['symbol'] == 'USDJPY' and usd_strength >= 2 and r['direction'] == 'BUY':
            bonus += 1
        spread_penalty = 1 if (r['spread'] is not None and r['atr_h1'] and r['spread'] / r['atr_h1'] > 0.08) else 0
        r['final_score'] = r['score'] + bonus - spread_penalty
    ranked = sorted([r for r in res if r.get('available')], key=lambda x: (x.get('final_score', 0), x.get('rr_est') or 0), reverse=True)
    def clean(obj):
        if isinstance(obj, dict):
            return {str(k): clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [clean(v) for v in obj]
        if hasattr(obj, 'item'):
            try:
                return obj.item()
            except Exception:
                pass
        return obj
    print(json.dumps(clean({'ok': True, 'risk_on': risk_on, 'risk_off': risk_off, 'usd_strength': usd_strength, 'ranked': ranked}), ensure_ascii=False))
finally:
    mt5.shutdown()
