import csv
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from urllib.request import urlopen

import MetaTrader5 as mt5

BASE_DIR = Path(r"C:\Users\Administrator\AppData\Local\hermes\trading")
JOURNAL_DIR = BASE_DIR / "journal"
REPORT_DIR = BASE_DIR / "reports"
STATE_PATH = BASE_DIR / "engine_state.json"
JOURNAL_CSV = JOURNAL_DIR / "trades.csv"
EVENTS_CSV = JOURNAL_DIR / "events.csv"
NEWS_CACHE = BASE_DIR / "news_cache.json"
DEFAULT_DEVIATION = 20
MAGIC = 20260806
ENGINE_LABEL = 'Hermes'
ENGINE_COMMENTS = {'Hermes auto', 'Hermes partial close', 'Hermes engine'}
FILLING_CANDIDATES = [
    mt5.ORDER_FILLING_IOC,
    getattr(mt5, "ORDER_FILLING_RETURN", mt5.ORDER_FILLING_IOC),
    getattr(mt5, "ORDER_FILLING_FOK", mt5.ORDER_FILLING_IOC),
]
SYMBOLS = ["XAUUSD"]
AUTO_TRADE_SYMBOLS = {"XAUUSD"}
ASSET_PRESETS = {
    "forex": {"risk_pct": 0.006, "sl_atr_mult": 1.8, "tp_atr_mult": 3.6, "max_spread_atr": 0.18, "be_rr": 0.9, "trail_atr": 1.2},
    "gold": {"risk_pct": 0.005, "sl_atr_mult": 0.8, "tp_atr_mult": 1.6, "max_spread_atr": 0.12, "be_rr": 0.7, "trail_atr": 0.8},
    "index": {"risk_pct": 0.004, "sl_atr_mult": 1.2, "tp_atr_mult": 2.4, "max_spread_atr": 0.08, "be_rr": 0.7, "trail_atr": 0.9},
    "crypto": {"risk_pct": 0.0035, "sl_atr_mult": 1.4, "tp_atr_mult": 2.8, "max_spread_atr": 0.12, "be_rr": 0.8, "trail_atr": 1.0},
}
SESSION_WINDOWS = {"asia": (0, 7), "london": (7, 13), "newyork": (13, 21)}
ALLOWED_SESSIONS = {
    "forex": {"london", "newyork"},
    "gold": {"asia", "london", "newyork"},
    "index": {"newyork", "london"},
    "crypto": {"asia", "london", "newyork"},
}
EXECUTION_THRESHOLDS = {
    "forex": {"trade": 60, "strong_watch": 55},
    "gold": {"trade": 56, "strong_watch": 50},
    "index": {"trade": 60, "strong_watch": 55},
    "crypto": {"trade": 60, "strong_watch": 55},
}
SYMBOL_COOLDOWN_MIN = {
    "forex": 10,
    "gold": 10,
    "index": 10,
    "crypto": 10,
}
POST_LOSS_COOLDOWN_MIN = 15
REENTRY_SAME_DIRECTION_LIMIT = 99
HIGH_IMPACT_FREEZE_HOURS = 1.0
MEDIUM_IMPACT_FREEZE_HOURS = 0.5
MAX_TICK_AGE_SEC = 90
MAX_BAR_AGE_MULTIPLIER = 1.6
VOLATILITY_BURST_MULTIPLIER = 2.4
SPREAD_SPIKE_MULTIPLIER = 1.8
DAILY_LOSS_LIMIT_PCT = 0.02
MIN_BIAS_FOR_TRADE = 1
MIN_SETUP_SCORE_FOR_TRADE = 48
MIN_RISK_USD = 8.0
MIN_REWARD_USD = 16.0
XAU_MIN_LOT_MAX_RISK_USD = 16.0


def ensure_dirs():
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def to_jsonable(obj):
    if obj is None:
        return None
    if hasattr(obj, '_asdict'):
        return {k: to_jsonable(v) for k, v in obj._asdict().items()}
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj


def fail(msg, **extra):
    print(json.dumps({"ok": False, "error": msg, **extra}, ensure_ascii=False))
    sys.exit(1)


def ensure_init():
    ensure_dirs()
    if not mt5.initialize():
        fail("mt5 initialize failed", last_error=mt5.last_error())


def shutdown():
    try:
        mt5.shutdown()
    except Exception:
        pass


def symbol_info(symbol):
    info = mt5.symbol_info(symbol)
    if info is None:
        return None
    if not info.visible:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
    return info


def normalize_volume(symbol, volume):
    info = symbol_info(symbol)
    step = info.volume_step or 0.01
    vol = max(info.volume_min, min(info.volume_max, float(volume)))
    step_dec = Decimal(str(step))
    vol_dec = (Decimal(str(vol)) / step_dec).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_dec
    return float(vol_dec)


def get_tick(symbol):
    return mt5.symbol_info_tick(symbol)


def get_asset_class(symbol):
    if symbol == "XAUUSD" or symbol.startswith("XAU"):
        return "gold"
    if symbol in ("BTCUSD", "ETHUSD"):
        return "crypto"
    if symbol in ("SPXUSD", "DJIUSD", "DAXEUR"):
        return "index"
    return "forex"


def rates(symbol, timeframe, count):
    data = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if data is None:
        return []
    return [dict(time=int(r['time']), open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close'])) for r in data]


def sma(values, n):
    return sum(values[-n:]) / n if len(values) >= n else None


def atr(rows, n=14):
    if len(rows) < n + 1:
        return None
    trs = []
    prev_close = rows[0]['close']
    for r in rows[1:]:
        tr = max(r['high'] - r['low'], abs(r['high'] - prev_close), abs(r['low'] - prev_close))
        trs.append(tr)
        prev_close = r['close']
    return sum(trs[-n:]) / n if len(trs) >= n else None


def timeframe_seconds(timeframe):
    mapping = {
        mt5.TIMEFRAME_M15: 15 * 60,
        mt5.TIMEFRAME_H1: 60 * 60,
        mt5.TIMEFRAME_H4: 4 * 60 * 60,
    }
    return mapping.get(timeframe, 60 * 60)


def session_name():
    h = datetime.now(timezone.utc).hour
    for name, (start, end) in SESSION_WINDOWS.items():
        if start <= h < end:
            return name
    return "newyork"


def fetch_news():
    now = datetime.now(timezone.utc)
    if NEWS_CACHE.exists():
        try:
            cached = json.loads(NEWS_CACHE.read_text(encoding='utf-8'))
            ts = datetime.fromisoformat(cached.get('fetched_at'))
            if now - ts < timedelta(minutes=30):
                return cached
        except Exception:
            pass
    url = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
    events = []
    try:
        with urlopen(url, timeout=20) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        for ev in payload:
            impact = (ev.get('impact') or '').lower()
            if impact in ('high', 'medium'):
                events.append({'title': ev.get('title'), 'country': ev.get('country'), 'impact': impact, 'date': ev.get('date')})
        data = {'fetched_at': now.isoformat(), 'events': events}
        NEWS_CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return data
    except Exception as e:
        return {'fetched_at': now.isoformat(), 'events': [], 'error': str(e)}


def symbol_news_risk(symbol, news):
    mapping = {
        'EURUSD': {'EUR', 'USD'}, 'GBPUSD': {'GBP', 'USD'}, 'USDJPY': {'USD', 'JPY'},
        'XAUUSD': {'USD', 'All'}, 'SPXUSD': {'USD', 'All'}, 'DJIUSD': {'USD', 'All'},
        'BTCUSD': {'USD', 'All'}, 'ETHUSD': {'USD', 'All'}, 'DAXEUR': {'EUR', 'All'},
    }
    wanted = mapping.get(symbol, {'All'})
    hits = []
    now = datetime.now(timezone.utc)
    for ev in news.get('events', []):
        try:
            dt = datetime.fromisoformat(ev['date'].replace('Z', '+00:00')).astimezone(timezone.utc)
        except Exception:
            continue
        hours = abs((dt - now).total_seconds()) / 3600.0
        if hours <= 12 and ev['country'] in wanted:
            hits.append({'title': ev['title'], 'country': ev['country'], 'impact': ev['impact'], 'hours': round(hours, 2)})
    return hits


def news_freeze_level(news_hits):
    freeze = None
    for hit in news_hits:
        impact = hit.get('impact')
        hours = float(hit.get('hours', 999))
        if impact == 'high' and hours <= HIGH_IMPACT_FREEZE_HOURS:
            freeze = 'high'
        elif impact == 'medium' and hours <= MEDIUM_IMPACT_FREEZE_HOURS and freeze != 'high':
            freeze = 'medium'
    return freeze


def adaptive_score_adjustment(symbol):
    return 0


def stronger_correlation_bonus(symbol, direction):
    if symbol == 'XAUUSD':
        return 0
    peers = {
        'SPXUSD': ['DJIUSD', 'DAXEUR'],
        'DJIUSD': ['SPXUSD', 'DAXEUR'],
        'DAXEUR': ['SPXUSD', 'DJIUSD'],
        'BTCUSD': ['ETHUSD'],
        'ETHUSD': ['BTCUSD'],
        'XAUUSD': ['EURUSD', 'USDJPY'],
    }
    rel = peers.get(symbol, [])
    if not rel or not direction:
        return 0
    score = 0
    for peer in rel:
        peer_rows = rates(peer, mt5.TIMEFRAME_H1, 30)
        if len(peer_rows) < 6:
            continue
        move = peer_rows[-1]['close'] - peer_rows[-6]['close']
        if symbol == 'XAUUSD' and peer == 'USDJPY':
            aligned = (direction == 'BUY' and move < 0) or (direction == 'SELL' and move > 0)
        else:
            aligned = (direction == 'BUY' and move > 0) or (direction == 'SELL' and move < 0)
        score += 4 if aligned else -2
    return score


def dynamic_thresholds(symbol, final_score, bias_strength, rr, session_allowed, spread_penalty, news_freeze, setup_score):
    asset = get_asset_class(symbol)
    base = EXECUTION_THRESHOLDS[asset]
    return {'trade': base['trade'], 'strong_watch': base['strong_watch']}


def execution_quality(symbol, tick, info, h1_atr, m15_rows):
    now_ts = datetime.now(timezone.utc).timestamp()
    tick_time = int(getattr(tick, 'time', 0) or 0)
    tick_age = max(0, now_ts - tick_time) if tick_time else None
    spread = abs((tick.ask or 0) - (tick.bid or 0))
    avg_recent_spread = spread
    burst = False
    bar_stale = False

    if len(m15_rows) >= 20:
        ranges = [abs(r['high'] - r['low']) for r in m15_rows[-20:-1]]
        avg_range = (sum(ranges) / len(ranges)) if ranges else 0
        last_range = abs(m15_rows[-1]['high'] - m15_rows[-1]['low'])
        burst = avg_range > 0 and last_range >= avg_range * VOLATILITY_BURST_MULTIPLIER
        bar_age = now_ts - int(m15_rows[-1]['time'])
        bar_stale = bar_age > (timeframe_seconds(mt5.TIMEFRAME_M15) * MAX_BAR_AGE_MULTIPLIER)

    ticks = mt5.copy_ticks_from(symbol, datetime.now(timezone.utc) - timedelta(minutes=3), 200, mt5.COPY_TICKS_INFO)
    if ticks is not None and len(ticks) >= 20:
        spreads = [abs(float(t['ask']) - float(t['bid'])) for t in ticks if float(t['ask']) and float(t['bid'])]
        if spreads:
            avg_recent_spread = sum(spreads) / len(spreads)

    stale_tick = tick_age is not None and tick_age > MAX_TICK_AGE_SEC
    spread_spike = avg_recent_spread > 0 and spread >= avg_recent_spread * SPREAD_SPIKE_MULTIPLIER
    bad_spread = h1_atr and spread > h1_atr * ASSET_PRESETS[get_asset_class(symbol)]['max_spread_atr']
    blocked = stale_tick or bar_stale or spread_spike or burst or bad_spread
    reasons = []
    if stale_tick:
        reasons.append('stale_tick')
    if bar_stale:
        reasons.append('stale_bar')
    if spread_spike:
        reasons.append('spread_spike')
    if burst:
        reasons.append('volatility_burst')
    if bad_spread:
        reasons.append('bad_spread')
    return {
        'ok': not blocked,
        'blocked': blocked,
        'reasons': reasons,
        'tick_age_sec': round(tick_age, 1) if tick_age is not None else None,
        'spread_now': spread,
        'spread_avg': round(avg_recent_spread, 6) if avg_recent_spread is not None else None,
    }


def symbol_in_cooldown(state, symbol, direction):
    cd = state.get('cooldowns', {}).get(symbol)
    if cd:
        until = parse_iso(cd.get('until', ''))
        if until and until > datetime.now():
            return True, cd.get('reason', 'cooldown')
    opens = recent_events(symbol=symbol, event='opened', hours=24)
    if opens:
        last_open = parse_iso(opens[-1]['timestamp'])
        if last_open and (datetime.now() - last_open) < timedelta(minutes=SYMBOL_COOLDOWN_MIN[get_asset_class(symbol)]):
            return True, 'symbol_cooldown'
    if direction:
        same_dir = [e for e in recent_events(symbol=symbol, event='opened', hours=24) if direction in (e.get('details') or '')]
        if len(same_dir) >= REENTRY_SAME_DIRECTION_LIMIT:
            return True, 'same_direction_retry_limit'
    return False, None


def analyze_symbol(symbol, news):
    info = symbol_info(symbol)
    tick = get_tick(symbol)
    if info is None or tick is None:
        return {'symbol': symbol, 'ok': False, 'error': 'symbol_or_tick_unavailable'}
    analysis = {'symbol': symbol, 'asset_class': get_asset_class(symbol), 'timeframes': {}, 'ok': True}
    tf_rows = {}
    for name, tf in {'M15': mt5.TIMEFRAME_M15, 'H1': mt5.TIMEFRAME_H1, 'H4': mt5.TIMEFRAME_H4}.items():
        rows = rates(symbol, tf, 260)
        tf_rows[name] = rows
        if len(rows) < 80:
            analysis['timeframes'][name] = {'error': 'not_enough_data'}
            continue
        closes = [r['close'] for r in rows]
        highs = [r['high'] for r in rows]
        lows = [r['low'] for r in rows]
        last = closes[-1]
        a = atr(rows, 14) or 0.0
        sma20 = sma(closes, 20); sma50 = sma(closes, 50); sma200 = sma(closes, 200)
        hi20 = max(highs[-20:]); lo20 = min(lows[-20:]); hi50 = max(highs[-50:]); lo50 = min(lows[-50:])
        trend = 'mixed'
        if sma20 and sma50 and sma200:
            if last > sma20 > sma50 > sma200:
                trend = 'bull'
            elif last < sma20 < sma50 < sma200:
                trend = 'bear'
        momentum = last - closes[-6]
        compression = (hi20 - lo20) < max(a * 4, info.point * 10)
        breakout = trend == 'bull' and last >= hi20 - a * 0.2
        breakdown = trend == 'bear' and last <= lo20 + a * 0.2
        pd_zone = 'discount' if last < ((hi50 + lo50) / 2.0) else 'premium'
        liquidity_sweep = (rows[-2]['high'] > hi20 and last < rows[-2]['high']) or (rows[-2]['low'] < lo20 and last > rows[-2]['low'])
        pullback_quality = 1.0 if (trend == 'bull' and pd_zone == 'discount') or (trend == 'bear' and pd_zone == 'premium') else 0.0
        breakout_quality = 1.0 if breakout or breakdown else 0.0
        score = 0
        score += 20 if trend != 'mixed' else 5
        score += 15 if momentum * (1 if trend == 'bull' else -1 if trend == 'bear' else 0) > 0 else 5
        score += 15 if liquidity_sweep else 5
        score += 10 if pullback_quality else 4
        score += 10 if breakout_quality else 4
        score += 10 if not compression else 4
        score += 10 if a > info.point * 20 else 5
        analysis['timeframes'][name] = {'last': last, 'atr14': a, 'trend': trend, 'momentum6': momentum, 'compression': compression, 'breakout': breakout, 'breakdown': breakdown, 'pd_zone': pd_zone, 'liquidity_sweep': liquidity_sweep, 'pullback_quality': pullback_quality, 'breakout_quality': breakout_quality, 'score': score, 'hi20': hi20, 'lo20': lo20, 'hi50': hi50, 'lo50': lo50}
    h4 = analysis['timeframes'].get('H4', {})
    h1 = analysis['timeframes'].get('H1', {})
    m15 = analysis['timeframes'].get('M15', {})
    long_bias = (h4.get('trend') == 'bull') + (h1.get('trend') == 'bull') + (m15.get('trend') == 'bull')
    short_bias = (h4.get('trend') == 'bear') + (h1.get('trend') == 'bear') + (m15.get('trend') == 'bear')
    direction = 'BUY' if long_bias > short_bias else 'SELL' if short_bias > long_bias else None
    bias_strength = max(long_bias, short_bias)
    setup_score = min(100, int((h4.get('score', 0) * 0.4) + (h1.get('score', 0) * 0.35) + (m15.get('score', 0) * 0.25)))
    preset = ASSET_PRESETS[get_asset_class(symbol)]
    h1_atr = h1.get('atr14') or info.point * 100
    sl_distance = max(h1_atr * preset['sl_atr_mult'], info.point * 50)
    tp_distance = max(h1_atr * preset['tp_atr_mult'], info.point * 80)
    rr = tp_distance / sl_distance if sl_distance else 0
    rr_quality = 18 if rr >= 2.0 else 10 if rr >= 1.4 else 0
    spread = abs((tick.ask or 0) - (tick.bid or 0))
    spread_penalty = 0 if (h1_atr and spread <= h1_atr * preset['max_spread_atr']) else 10
    current_session = session_name()
    allowed_sessions = ALLOWED_SESSIONS[get_asset_class(symbol)]
    session_allowed = current_session in allowed_sessions
    news_hits = symbol_news_risk(symbol, news)
    news_freeze = news_freeze_level(news_hits)
    exec_quality = execution_quality(symbol, tick, info, h1_atr, tf_rows.get('M15', []))
    correlation = 0
    if symbol in ('SPXUSD', 'DJIUSD'):
        peer = 'DJIUSD' if symbol == 'SPXUSD' else 'SPXUSD'
        peer_rows = rates(peer, mt5.TIMEFRAME_H1, 30); own_rows = rates(symbol, mt5.TIMEFRAME_H1, 30)
        if len(peer_rows) > 5 and len(own_rows) > 5:
            correlation = 8 if (peer_rows[-1]['close'] - peer_rows[-6]['close']) * (own_rows[-1]['close'] - own_rows[-6]['close']) > 0 else -4
    elif symbol in ('BTCUSD', 'ETHUSD'):
        peer = 'ETHUSD' if symbol == 'BTCUSD' else 'BTCUSD'
        peer_rows = rates(peer, mt5.TIMEFRAME_H1, 30); own_rows = rates(symbol, mt5.TIMEFRAME_H1, 30)
        if len(peer_rows) > 5 and len(own_rows) > 5:
            correlation = 8 if (peer_rows[-1]['close'] - peer_rows[-6]['close']) * (own_rows[-1]['close'] - own_rows[-6]['close']) > 0 else -4
    correlation += stronger_correlation_bonus(symbol, direction)
    adaptive_adj = adaptive_score_adjustment(symbol)
    quality_penalty = 6 if exec_quality['blocked'] else 0
    news_penalty = 18 if news_freeze == 'high' else 10 if news_freeze == 'medium' else (12 if news_hits else 0)
    session_bonus = 5 if session_allowed else (-4 if symbol == 'XAUUSD' else -12)
    if symbol == 'XAUUSD' and direction and bias_strength >= 1 and setup_score >= 42 and exec_quality['ok'] and not news_freeze:
        session_bonus = max(session_bonus, 0)
    final_score = max(0, min(100, setup_score + rr_quality + correlation + session_bonus + adaptive_adj - spread_penalty - news_penalty - quality_penalty))
    thresholds = dynamic_thresholds(symbol, final_score, bias_strength, rr, session_allowed, spread_penalty, news_freeze, setup_score)
    state = 'watch'
    if symbol == 'XAUUSD' and direction and bias_strength >= MIN_BIAS_FOR_TRADE and setup_score >= MIN_SETUP_SCORE_FOR_TRADE and final_score >= thresholds['trade'] and rr >= 2.0 and not news_freeze and exec_quality['ok']:
        state = 'trade'
    elif direction and final_score >= thresholds['strong_watch']:
        state = 'watch_strong'
    analysis.update({'direction': direction, 'bias_strength': bias_strength, 'setup_score': setup_score, 'final_score': final_score, 'rr_estimate': round(rr, 2), 'sl_distance_price': sl_distance, 'tp_distance_price': tp_distance, 'spread': spread, 'state': state, 'news_hits': news_hits, 'news_freeze': news_freeze, 'adaptive_adj': adaptive_adj, 'correlation_bonus': correlation, 'execution_quality': exec_quality, 'thresholds': thresholds, 'session_allowed': session_allowed})
    return analysis


def get_account():
    acc = mt5.account_info()
    if acc is None:
        fail('account info unavailable', last_error=mt5.last_error())
    return acc


def point_value(symbol, info):
    tick = get_tick(symbol)
    if tick is None:
        return 0.0
    profit = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbol, 1.0, tick.ask, tick.ask + info.point)
    return abs(profit) if profit is not None else 0.0


def confidence_tier(score):
    if score >= 90:
        return {'name': 'A', 'risk_mult': 1.0, 'size_mult': 1.0, 'allow_pyramid': True}
    if score >= 80:
        return {'name': 'B', 'risk_mult': 0.8, 'size_mult': 0.8, 'allow_pyramid': False}
    if score >= 70:
        return {'name': 'C', 'risk_mult': 0.6, 'size_mult': 0.5, 'allow_pyramid': False}
    return {'name': 'D', 'risk_mult': 0.0, 'size_mult': 0.0, 'allow_pyramid': False}


def compute_lot(symbol, sl_distance_price, score):
    acc = get_account(); info = symbol_info(symbol); preset = ASSET_PRESETS[get_asset_class(symbol)]; tier = confidence_tier(score)
    risk_pct = preset['risk_pct'] * tier['risk_mult']
    value_per_point = point_value(symbol, info) or 1.0
    points = max(sl_distance_price / info.point, 1)
    risk_amount = acc.balance * risk_pct
    raw_lot = (risk_amount / (points * value_per_point)) * tier['size_mult'] if points > 0 else 0
    normalized = normalize_volume(symbol, raw_lot)
    if tier['risk_mult'] <= 0 or tier['size_mult'] <= 0 or risk_amount <= 0:
        return 0.0, risk_amount, tier
    if normalized <= 0:
        return 0.0, risk_amount, tier
    if normalized == info.volume_min and raw_lot < info.volume_min * 0.8:
        return 0.0, risk_amount, tier
    return normalized, risk_amount, tier


def trade_value_metrics(symbol, lot, entry_price, sl_price, tp_price):
    if lot <= 0:
        return {'risk_usd': 0.0, 'reward_usd': 0.0}
    order_type = mt5.ORDER_TYPE_BUY
    risk = mt5.order_calc_profit(order_type, symbol, lot, entry_price, sl_price) if sl_price else None
    reward = mt5.order_calc_profit(order_type, symbol, lot, entry_price, tp_price) if tp_price else None
    return {
        'risk_usd': round(abs(risk or 0.0), 2),
        'reward_usd': round(abs(reward or 0.0), 2),
    }


def candidate_trade_plan(best):
    info = symbol_info(best['symbol'])
    if info is None or not best.get('direction'):
        return {'ok': False, 'reason': 'missing_market_info'}
    sl_points = int(max(best['sl_distance_price'] / info.point, 20))
    tp_points = int(max(best['tp_distance_price'] / info.point, 30))
    lot, risk_amount, tier = compute_lot(best['symbol'], best['sl_distance_price'], best['final_score'])
    tick = get_tick(best['symbol'])
    if tick is None:
        return {'ok': False, 'reason': 'missing_tick'}
    if best['direction'] == 'BUY':
        entry_price = tick.ask
        sl_price = round(entry_price - sl_points * info.point, info.digits)
        tp_price = round(entry_price + tp_points * info.point, info.digits)
    else:
        entry_price = tick.bid
        sl_price = round(entry_price + sl_points * info.point, info.digits)
        tp_price = round(entry_price - tp_points * info.point, info.digits)
    value = trade_value_metrics(best['symbol'], lot, entry_price, sl_price, tp_price)
    auto_allowed = best['symbol'] in AUTO_TRADE_SYMBOLS
    reasons = []
    if best['symbol'] == 'XAUUSD' and lot <= 0 and info.volume_min > 0:
        min_lot_value = trade_value_metrics(best['symbol'], info.volume_min, entry_price, sl_price, tp_price)
        if min_lot_value['risk_usd'] > 0 and min_lot_value['risk_usd'] <= XAU_MIN_LOT_MAX_RISK_USD:
            lot = info.volume_min
            value = min_lot_value
            reasons.append('xau_min_lot_override')
    worth_it = lot > 0 and value['risk_usd'] >= MIN_RISK_USD and value['reward_usd'] >= MIN_REWARD_USD
    if not auto_allowed:
        reasons.append('observe_only_symbol')
    if lot <= 0:
        reasons.append('lot_too_small')
    if 0 < value['risk_usd'] < MIN_RISK_USD:
        reasons.append('risk_too_small')
    if 0 < value['reward_usd'] < MIN_REWARD_USD:
        reasons.append('reward_too_small')
    return {
        'ok': True,
        'symbol': best['symbol'],
        'direction': best['direction'],
        'lot': lot,
        'risk_amount': round(risk_amount, 2),
        'tier': tier,
        'sl_points': sl_points,
        'tp_points': tp_points,
        'entry_price': entry_price,
        'sl_price': sl_price,
        'tp_price': tp_price,
        'value': value,
        'auto_allowed': auto_allowed,
        'worth_it': worth_it,
        'reasons': reasons,
    }


def build_request(symbol, direction, lot, sl_points, tp_points, comment='Hermes engine'):
    info = symbol_info(symbol); tick = get_tick(symbol)
    if direction == 'BUY':
        order_type = mt5.ORDER_TYPE_BUY; price = tick.ask; sl = round(price - sl_points * info.point, info.digits) if sl_points > 0 else 0.0; tp = round(price + tp_points * info.point, info.digits) if tp_points > 0 else 0.0
    else:
        order_type = mt5.ORDER_TYPE_SELL; price = tick.bid; sl = round(price + sl_points * info.point, info.digits) if sl_points > 0 else 0.0; tp = round(price - tp_points * info.point, info.digits) if tp_points > 0 else 0.0
    return {'action': mt5.TRADE_ACTION_DEAL, 'symbol': symbol, 'volume': normalize_volume(symbol, lot), 'type': order_type, 'price': price, 'sl': sl, 'tp': tp, 'deviation': DEFAULT_DEVIATION, 'magic': MAGIC, 'comment': comment, 'type_time': mt5.ORDER_TIME_GTC, 'type_filling': mt5.ORDER_FILLING_IOC}


def validate_and_send(symbol, direction, lot, sl_points, tp_points, comment='Hermes engine'):
    attempts = []
    for include_stops in (True, False):
        for filling in FILLING_CANDIDATES:
            req = build_request(symbol, direction, lot, sl_points if include_stops else 0, tp_points if include_stops else 0, comment)
            req['type_filling'] = filling
            check = mt5.order_check(req)
            attempts.append({'request': req, 'check': to_jsonable(check), 'include_stops': include_stops, 'filling': filling})
            if check is not None and check.retcode == 0:
                result = mt5.order_send(req)
                out = {'ok': result is not None and result.retcode == mt5.TRADE_RETCODE_DONE, 'request': req, 'check': to_jsonable(check), 'result': to_jsonable(result), 'attempts': attempts}
                if out['ok'] and not include_stops and (sl_points > 0 or tp_points > 0):
                    positions = mt5.positions_get(symbol=symbol) or []
                    for p in positions:
                        if p.magic == MAGIC:
                            tick = get_tick(symbol); info = symbol_info(symbol)
                            mod_req = {'action': mt5.TRADE_ACTION_SLTP, 'symbol': symbol, 'position': p.ticket}
                            if direction == 'BUY':
                                mod_req['sl'] = round(tick.bid - sl_points * info.point, info.digits); mod_req['tp'] = round(tick.bid + tp_points * info.point, info.digits)
                            else:
                                mod_req['sl'] = round(tick.ask + sl_points * info.point, info.digits); mod_req['tp'] = round(tick.ask - tp_points * info.point, info.digits)
                            out['post_open_sltp'] = to_jsonable(mt5.order_send(mod_req)); break
                return out
    return {'ok': False, 'attempts': attempts, 'error': 'validation_failed'}


def modify_position(position, new_sl=None, new_tp=None):
    req = {'action': mt5.TRADE_ACTION_SLTP, 'symbol': position.symbol, 'position': position.ticket, 'sl': new_sl if new_sl is not None else position.sl, 'tp': new_tp if new_tp is not None else position.tp, 'magic': MAGIC}
    res = mt5.order_send(req)
    return {'request': req, 'result': to_jsonable(res), 'ok': res is not None and res.retcode == mt5.TRADE_RETCODE_DONE}


def partial_close(position, volume):
    tick = get_tick(position.symbol)
    direction = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if direction == mt5.ORDER_TYPE_SELL else tick.ask
    req = {'action': mt5.TRADE_ACTION_DEAL, 'symbol': position.symbol, 'volume': normalize_volume(position.symbol, volume), 'type': direction, 'position': position.ticket, 'price': price, 'deviation': DEFAULT_DEVIATION, 'magic': MAGIC, 'comment': 'Hermes partial close', 'type_time': mt5.ORDER_TIME_GTC, 'type_filling': mt5.ORDER_FILLING_IOC}
    res = mt5.order_send(req)
    return {'request': req, 'result': to_jsonable(res), 'ok': res is not None and res.retcode == mt5.TRADE_RETCODE_DONE}


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def is_engine_deal(deal):
    comment = str(getattr(deal, 'comment', '') or '')
    magic = int(getattr(deal, 'magic', 0) or 0)
    return magic == MAGIC or comment in ENGINE_COMMENTS


def get_engine_deals(days=7):
    deals = mt5.history_deals_get(datetime.now() - timedelta(days=days), datetime.now()) or []
    return [d for d in deals if is_engine_deal(d)]


def deal_close_key(deal):
    position_id = getattr(deal, 'position_id', None)
    if position_id:
        return str(position_id)
    order = getattr(deal, 'order', None)
    return str(order) if order else None


def log_trade(entry):
    exists = JOURNAL_CSV.exists()
    with JOURNAL_CSV.open('a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['timestamp','symbol','side','volume','entry_price','sl','tp','score','state','reason','ticket','status','pnl','session'])
        if not exists:
            writer.writeheader()
        writer.writerow(entry)


def log_event(event):
    exists = EVENTS_CSV.exists()
    with EVENTS_CSV.open('a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['timestamp','symbol','ticket','event','details'])
        if not exists:
            writer.writeheader()
        writer.writerow(event)


def update_trade_status(ticket, status=None, pnl=None, reason=None):
    if not JOURNAL_CSV.exists():
        return
    rows = list(csv.DictReader(JOURNAL_CSV.open('r', encoding='utf-8')))
    changed = False
    for r in rows:
        if str(r.get('ticket')) == str(ticket):
            if status is not None:
                r['status'] = status
            if pnl is not None:
                r['pnl'] = pnl
            if reason is not None:
                r['reason'] = f"{r.get('reason','')} | {reason}".strip(' |')
            changed = True
    if changed:
        with JOURNAL_CSV.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['timestamp','symbol','side','volume','entry_price','sl','tp','score','state','reason','ticket','status','pnl','session'])
            writer.writeheader()
            writer.writerows(rows)


def parse_iso(ts):
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def recent_events(symbol=None, event=None, hours=48):
    if not EVENTS_CSV.exists():
        return []
    cutoff = datetime.now() - timedelta(hours=hours)
    rows = list(csv.DictReader(EVENTS_CSV.open('r', encoding='utf-8')))
    out = []
    for r in rows:
        dt = parse_iso(r.get('timestamp', ''))
        if not dt or dt < cutoff:
            continue
        if symbol and r.get('symbol') != symbol:
            continue
        if event and r.get('event') != event:
            continue
        out.append(r)
    return out


def reconcile_closed_trades(state):
    open_tickets = {str(p.ticket) for p in (mt5.positions_get() or [])}
    rows = list(csv.DictReader(JOURNAL_CSV.open('r', encoding='utf-8'))) if JOURNAL_CSV.exists() else []
    engine_deals = get_engine_deals(14)
    close_by_key = {}
    for d in engine_deals:
        if getattr(d, 'entry', None) == 1:
            key = deal_close_key(d)
            if key:
                close_by_key[key] = d
    for r in rows:
        ticket = str(r.get('ticket', ''))
        if r.get('status') == 'opened' and ticket and ticket not in open_tickets:
            close_deal = close_by_key.get(ticket)
            pnl = float(getattr(close_deal, 'profit', 0.0)) if close_deal else 0.0
            comment = str(getattr(close_deal, 'comment', '')) if close_deal else 'closed'
            update_trade_status(ticket, status='closed', pnl=pnl, reason=comment)
            log_event({'timestamp': datetime.now().isoformat(), 'symbol': r.get('symbol'), 'ticket': ticket, 'event': 'closed', 'details': json.dumps({'pnl': pnl, 'comment': comment}, ensure_ascii=False)})
            state.get('positions', {}).pop(ticket, None)
            state.get('cooldowns', {}).pop(r.get('symbol'), None)
            if pnl < 0:
                state.setdefault('cooldowns', {})[r.get('symbol')] = {'until': (datetime.now() + timedelta(minutes=POST_LOSS_COOLDOWN_MIN)).isoformat(), 'reason': 'post_loss'}
    return state


def analytics():
    rows = []
    if JOURNAL_CSV.exists():
        rows = list(csv.DictReader(JOURNAL_CSV.open('r', encoding='utf-8')))
    history_closes = []
    for d in get_engine_deals(14):
        if getattr(d, 'entry', None) == 1:
            history_closes.append({
                'symbol': getattr(d, 'symbol', ''),
                'pnl': float(getattr(d, 'profit', 0.0) or 0.0),
            })
    pnls = [float(r.get('pnl') or 0) for r in rows if str(r.get('pnl', '')).strip() not in ('', '0', '0.0')] + [x['pnl'] for x in history_closes]
    trades = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total_pnl = sum(pnls)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else None
    return {
        'trades': trades,
        'win_rate': round((len(wins) / trades) * 100, 2) if trades else 0,
        'total_pnl': round(total_pnl, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_factor': round(pf, 2) if pf is not None else None,
    }


def should_skip_symbol(best, snapshot):
    if not best:
        return None
    open_symbols = set(snapshot.get('symbols_with_positions', []))
    if best.get('symbol') in open_symbols:
        return 'already_open_symbol'
    asset = best.get('asset_class')
    return None


def account_snapshot():
    acc = get_account(); positions = mt5.positions_get() or []
    return {'balance': acc.balance, 'equity': acc.equity, 'margin_free': acc.margin_free, 'positions_total': len(positions), 'symbols_with_positions': sorted({p.symbol for p in positions})}


def update_daily_state_from_history(state):
    today = datetime.now().strftime('%Y-%m-%d')
    daily = state.setdefault('daily', {})
    if today not in daily:
        daily[today] = {'realized_pnl': 0.0, 'loss_streak': 0, 'trades': 0}
    deals = get_engine_deals(2)
    pnl = 0.0; streak = 0; trade_count = 0
    for d in deals:
        if getattr(d, 'entry', None) == 1:
            trade_count += 1
            p = float(getattr(d, 'profit', 0.0)); pnl += p
            streak = streak + 1 if p < 0 else 0 if p > 0 else streak
    daily[today] = {'realized_pnl': round(pnl, 2), 'loss_streak': streak, 'trades': trade_count}
    return state


def guardrails(state, snapshot):
    today = datetime.now().strftime('%Y-%m-%d')
    ds = state.get('daily', {}).get(today, {'realized_pnl': 0.0, 'loss_streak': 0, 'trades': 0})
    bal = float(snapshot.get('balance') or 0)
    daily_loss_limit_value = bal * DAILY_LOSS_LIMIT_PCT if bal > 0 else 0
    if daily_loss_limit_value > 0 and ds['realized_pnl'] <= -daily_loss_limit_value:
        return {'allowed': False, 'reason': 'daily_loss_limit'}
    if snapshot['positions_total'] >= 2:
        return {'allowed': False, 'reason': 'max_open_positions'}
    return {'allowed': True}


def manage_positions(news, state):
    managed = []
    positions = mt5.positions_get() or []
    for p in positions:
        asset = get_asset_class(p.symbol); preset = ASSET_PRESETS[asset]; info = symbol_info(p.symbol); tick = get_tick(p.symbol)
        if info is None or tick is None:
            continue
        h1_rows = rates(p.symbol, mt5.TIMEFRAME_H1, 80); h1_atr = atr(h1_rows, 14) or (info.point * 100)
        price_now = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
        current_profit_price = (price_now - p.price_open) if p.type == mt5.POSITION_TYPE_BUY else (p.price_open - price_now)
        risk_price = abs(p.price_open - p.sl) if p.sl else h1_atr * preset['sl_atr_mult']
        rr_progress = current_profit_price / risk_price if risk_price > 0 else 0
        sym_state = state.setdefault('positions', {}).setdefault(str(p.ticket), {'partial_done': False, 'be_done': False, 'pyramid_count': 0})
        news_hits = symbol_news_risk(p.symbol, news)
        # reduce risk on news proximity
        if news_hits and p.sl != p.price_open:
            be_price = p.price_open
            res = modify_position(p, new_sl=be_price)
            managed.append({'ticket': p.ticket, 'action': 'news_reduce_risk', 'ok': res['ok']})
            log_event({'timestamp': datetime.now().isoformat(), 'symbol': p.symbol, 'ticket': p.ticket, 'event': 'news_reduce_risk', 'details': json.dumps({'hours': news_hits[0].get('hours') if news_hits else None}, ensure_ascii=False)})
            sym_state['be_done'] = True
        # break-even move
        if rr_progress >= preset['be_rr'] and not sym_state['be_done']:
            be_price = p.price_open + (info.point * 3 if p.type == mt5.POSITION_TYPE_BUY else -info.point * 3)
            res = modify_position(p, new_sl=round(be_price, info.digits))
            managed.append({'ticket': p.ticket, 'action': 'breakeven', 'ok': res['ok']})
            log_event({'timestamp': datetime.now().isoformat(), 'symbol': p.symbol, 'ticket': p.ticket, 'event': 'breakeven', 'details': json.dumps({'new_sl': round(be_price, info.digits)}, ensure_ascii=False)})
            sym_state['be_done'] = True
        # partial close
        if rr_progress >= 1.5 and not sym_state['partial_done'] and p.volume > info.volume_min:
            close_vol = max(info.volume_min, normalize_volume(p.symbol, p.volume / 2.0))
            if close_vol < p.volume:
                res = partial_close(p, close_vol)
                managed.append({'ticket': p.ticket, 'action': 'partial_close', 'ok': res['ok'], 'volume': close_vol})
                log_event({'timestamp': datetime.now().isoformat(), 'symbol': p.symbol, 'ticket': p.ticket, 'event': 'partial_close', 'details': json.dumps({'volume': close_vol}, ensure_ascii=False)})
                sym_state['partial_done'] = True
        # trailing by ATR / structure
        if rr_progress >= 1.0:
            trail_dist = h1_atr * preset['trail_atr']
            if p.type == mt5.POSITION_TYPE_BUY:
                swing_low = min(r['low'] for r in h1_rows[-5:]) if len(h1_rows) >= 5 else price_now - trail_dist
                new_sl = max(p.sl or 0.0, round(min(price_now - trail_dist, swing_low), info.digits))
                if new_sl > (p.sl or 0.0):
                    res = modify_position(p, new_sl=new_sl)
                    managed.append({'ticket': p.ticket, 'action': 'trail_buy', 'ok': res['ok'], 'new_sl': new_sl})
                    log_event({'timestamp': datetime.now().isoformat(), 'symbol': p.symbol, 'ticket': p.ticket, 'event': 'trail_buy', 'details': json.dumps({'new_sl': new_sl}, ensure_ascii=False)})
            else:
                swing_high = max(r['high'] for r in h1_rows[-5:]) if len(h1_rows) >= 5 else price_now + trail_dist
                current_sl = p.sl if p.sl else 10**9
                new_sl = min(current_sl, round(max(price_now + trail_dist, swing_high), info.digits))
                if new_sl < current_sl:
                    res = modify_position(p, new_sl=new_sl)
                    managed.append({'ticket': p.ticket, 'action': 'trail_sell', 'ok': res['ok'], 'new_sl': new_sl})
                    log_event({'timestamp': datetime.now().isoformat(), 'symbol': p.symbol, 'ticket': p.ticket, 'event': 'trail_sell', 'details': json.dumps({'new_sl': new_sl}, ensure_ascii=False)})
        state['positions'][str(p.ticket)] = sym_state
    return managed, state


def watchlist(news):
    ranked = sorted([a for a in (analyze_symbol(s, news) for s in SYMBOLS) if a.get('ok')], key=lambda x: x.get('final_score', 0), reverse=True)
    return ranked


def execute_best(full_auto=False):
    news = fetch_news(); state = load_state(); state = reconcile_closed_trades(state); state = update_daily_state_from_history(state)
    snapshot = account_snapshot(); guards = guardrails(state, snapshot)
    managed, state = manage_positions(news, state)
    ranked = watchlist(news)
    report = {'ok': True, 'snapshot': snapshot, 'guards': guards, 'managed': managed, 'top': ranked[:5], 'analytics': analytics(), 'session': session_name(), 'news_count': len(news.get('events', []))}
    action = {'taken': False}
    executable = None
    observed_best = ranked[0] if ranked else None
    if not guards['allowed']:
        blocked_symbol = ranked[0]['symbol'] if ranked else None
        action = {'taken': False, 'blocked': f"guard:{guards['reason']}", 'symbol': blocked_symbol}
    elif ranked:
        best = next((r for r in ranked if r.get('direction') and r.get('state') == 'trade'), ranked[0])
        executable = best
        exposure_blocked = should_skip_symbol(best, snapshot)
        already_positions = mt5.positions_get(symbol=best['symbol']) or []
        plan = candidate_trade_plan(best) if best.get('direction') else {'ok': False, 'reason': 'missing_direction'}
        tier = plan.get('tier', confidence_tier(best.get('final_score', 0)))
        allow_pyramid = tier['allow_pyramid'] and len(already_positions) == 1 and best.get('bias_strength', 0) >= 3
        cooldown_blocked, cooldown_reason = symbol_in_cooldown(state, best['symbol'], best.get('direction'))
        can_open = full_auto and best.get('state') == 'trade' and best.get('direction') and best.get('session_allowed') and not cooldown_blocked and not exposure_blocked and (not already_positions or allow_pyramid) and plan.get('ok') and plan.get('auto_allowed') and plan.get('worth_it')
        if can_open:
            if plan.get('lot', 0) > 0:
                result = validate_and_send(best['symbol'], best['direction'], plan['lot'], plan['sl_points'], plan['tp_points'], 'Hermes auto')
                action = {'taken': result.get('ok', False), 'symbol': best['symbol'], 'direction': best['direction'], 'lot': plan['lot'], 'score': best['final_score'], 'tier': tier['name'], 'risk_amount': plan.get('risk_amount', 0), 'value': plan.get('value'), 'result': result}
                if result.get('ok'):
                    ticket = (((result.get('result') or {}).get('order')) if isinstance(result.get('result'), dict) else None)
                    log_trade({'timestamp': datetime.now().isoformat(), 'symbol': best['symbol'], 'side': best['direction'], 'volume': plan['lot'], 'entry_price': result['result'].get('price') if result.get('result') else '', 'sl': result['request'].get('sl') if result.get('request') else '', 'tp': result['request'].get('tp') if result.get('request') else '', 'score': best['final_score'], 'state': best['state'], 'reason': f"bias={best['bias_strength']} rr={best['rr_estimate']} tier={tier['name']} news={len(best['news_hits'])} value={plan.get('value')}", 'ticket': ticket, 'status': 'opened', 'pnl': 0, 'session': session_name()})
                    log_event({'timestamp': datetime.now().isoformat(), 'symbol': best['symbol'], 'ticket': ticket, 'event': 'opened', 'details': json.dumps({'direction': best['direction'], 'score': best['final_score'], 'tier': tier['name']}, ensure_ascii=False)})
                    state.setdefault('cooldowns', {})[best['symbol']] = {'until': (datetime.now() + timedelta(minutes=SYMBOL_COOLDOWN_MIN[get_asset_class(best['symbol'])])).isoformat(), 'reason': 'post_open'}
        elif cooldown_blocked:
            action = {'taken': False, 'blocked': cooldown_reason, 'symbol': best['symbol']}
        elif exposure_blocked:
            action = {'taken': False, 'blocked': exposure_blocked, 'symbol': best['symbol']}
        elif best.get('state') == 'trade' and best.get('direction') and plan.get('ok'):
            blocked = plan.get('reasons', ['not_executable'])[0]
            action = {'taken': False, 'blocked': blocked, 'symbol': best['symbol'], 'plan': plan}
    report['observed_best'] = observed_best
    report['executable_candidate'] = executable
    report['action'] = action
    save_state(state)
    report_path = REPORT_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def brief_report(report):
    top = report.get('top', [])
    best = report.get('executable_candidate') or report.get('observed_best') or (top[0] if top else {})
    snapshot = report.get('snapshot', {})
    action = report.get('action', {})
    managed = report.get('managed', [])
    analytics_data = report.get('analytics', {})

    guard_reason = report.get('guards', {}).get('reason')
    balance = float(snapshot.get('balance') or 0)
    daily_loss_limit_value = round(balance * DAILY_LOSS_LIMIT_PCT, 2) if balance > 0 else 0
    guard_fa = {
        'loss_streak_limit': 'محدودیت استریک ضرر',
        'daily_loss_limit': f'محدودیت ضرر روزانه ({int(DAILY_LOSS_LIMIT_PCT*100)}٪ ~= {daily_loss_limit_value})',
        'daily_trade_cap': 'سقف معاملات روزانه',
        'max_open_positions': 'سقف پوزیشن باز',
    }.get(guard_reason, 'ok' if report.get('guards', {}).get('allowed') else guard_reason)

    lines = [
        f"• حساب | Bal: {snapshot.get('balance')} | Eq: {snapshot.get('equity')} | Open: {snapshot.get('positions_total')}",
        f"• وضعیت روز | Trades: {analytics_data.get('trades', 0)} | PnL: {analytics_data.get('total_pnl', 0)} | Guard: {guard_reason or 'ok'} ({guard_fa})",
    ]

    if best:
        lines.append(f"• ستاپ فعال | {best.get('symbol')} {best.get('direction') or 'WAIT'} | Score: {best.get('final_score')} | State: {best.get('state')}")
        lines.append(f"• منطق | Bias: {best.get('bias_strength')} | RR: {best.get('rr_estimate')} | Session: {('ok' if best.get('session_allowed') else 'weak')}")
        why = []
        if best.get('bias_strength', 0) >= MIN_BIAS_FOR_TRADE:
            why.append('بایاس قوی')
        elif best.get('bias_strength', 0) >= 1:
            why.append('بایاس ضعیف')
        if (best.get('rr_estimate') or 0) >= 1.7:
            why.append('RR خوب')
        if (best.get('correlation_bonus') or 0) > 0:
            why.append('همبستگی مثبت')
        if (best.get('setup_score') or 0) < MIN_SETUP_SCORE_FOR_TRADE:
            why.append('ساختار ستاپ ضعیف')
        exec_quality = best.get('execution_quality') or {}
        if exec_quality.get('blocked') and exec_quality.get('reasons'):
            fa_map = {
                'stale_tick': 'تیک قدیمی',
                'stale_bar': 'کندل قدیمی',
                'spread_spike': 'جهش اسپرد',
                'volatility_burst': 'جهش نوسان',
                'bad_spread': 'اسپرد نامناسب',
            }
            why.append('فیلتر اجرا: ' + '، '.join(fa_map.get(x, x) for x in exec_quality.get('reasons', [])[:2]))
        if best.get('thresholds'):
            gap = round((best['thresholds'].get('trade', 0) - best.get('final_score', 0)), 1)
            if gap > 0:
                why.append(f'{gap} نمره تا ورود')
        lines.append(f"• دلیل | {(' + '.join(why[:3])) if why else 'ستاپ متوسط'}")


    if action.get('taken'):
        value = action.get('value') or {}
        lines.append(f"• اقدام | {action.get('direction')} {action.get('symbol')} | Lot: {action.get('lot')} | TP$: {value.get('reward_usd')} | SL$: {value.get('risk_usd')}")
    elif action.get('blocked'):
        blocked = str(action.get('blocked'))
        if blocked.startswith('guard:'):
            reason = blocked.split(':', 1)[1]
            reason_fa = {
                'loss_streak_limit': 'محدودیت استریک ضرر',
                'daily_loss_limit': f'محدودیت ضرر روزانه ({int(DAILY_LOSS_LIMIT_PCT*100)}٪)',
                'daily_trade_cap': 'سقف معاملات روزانه',
                'max_open_positions': 'سقف پوزیشن باز',
            }.get(reason, 'محدودیت ریسک')
            lines.append(f"• اقدام | ورود انجام نشد | Reason: {reason} ({reason_fa}) | Symbol: {action.get('symbol')}")
        else:
            blocked_fa = {
                'already_open_symbol': 'روی همین نماد پوزیشن باز است',
                'post_open': 'بعد از ورود اخیر، ورود مجدد موقتاً متوقف است',
                'symbol_cooldown': 'نماد در cooldown است',
                'same_direction_retry_limit': 'تکرار ورود همجهت زیاد شده',
                'tier_blocked': 'سطح اطمینان کافی نیست',
                'observe_only_symbol': 'این نماد فقط برای رصد است، نه ورود خودکار',
                'lot_too_small': 'حجم موثر برای این ستاپ/حساب به دست نیامد',
                'risk_too_small': f'ریسک دلاری این معامله کم است (< {MIN_RISK_USD}$)',
                'reward_too_small': f'سود بالقوه این معامله کم است (< {MIN_REWARD_USD}$)',
            }.get(blocked, 'ورود فعلاً متوقف شد')
            lines.append(f"• اقدام | ورود انجام نشد | Reason: {blocked} ({blocked_fa}) | Symbol: {action.get('symbol')}")
    else:
        lines.append("• اقدام | no new trade / معامله جدیدی باز نشد")

    return '\n'.join(lines[:6])


def main(argv):
    if len(argv) < 2:
        fail('usage: status|scan|auto|analytics|journal|manage')
    ensure_init()
    try:
        cmd = argv[1].lower()
        if cmd == 'status':
            print(json.dumps(account_snapshot(), ensure_ascii=False))
        elif cmd == 'scan':
            print(json.dumps(execute_best(full_auto=False), ensure_ascii=False))
        elif cmd == 'auto':
            print(brief_report(execute_best(full_auto=True)))
        elif cmd == 'analytics':
            print(json.dumps(analytics(), ensure_ascii=False))
        elif cmd == 'journal':
            print(json.dumps({'journal_csv': str(JOURNAL_CSV), 'exists': JOURNAL_CSV.exists()}, ensure_ascii=False))
        elif cmd == 'manage':
            news = fetch_news(); state = load_state(); managed, state = manage_positions(news, state); save_state(state); print(json.dumps({'ok': True, 'managed': managed}, ensure_ascii=False))
        else:
            fail('unknown command', command=cmd)
    finally:
        shutdown()


if __name__ == '__main__':
    main(sys.argv)
