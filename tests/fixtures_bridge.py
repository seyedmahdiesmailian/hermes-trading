"""b36 — ONE production-shaped source of bridge payloads for the whole suite.

Why this file exists: every MockBridge/FakeBridge in tests/ hand-rolled its
own payloads, and NONE of them ever returned a position — that is exactly why
the b34 crash (int('SELL') on the real /api/positions wire shape) survived to
production. A hand-rolled fake can silently disagree with the producer; the
fix is a single fixture module whose builders mirror
scripts/mt5_http_server_v2.py FIELD-FOR-FIELD, plus a drift test
(tests/test_b36_bridge_fixtures.py) that AST-parses the server source and
fails if the fixture shape and the producer shape ever disagree again.

Ground rules baked into these builders (all measured from the server source):
  * /api/positions 'type' is the STRING 'BUY'/'SELL' (never the MT5 int) —
    unless a test deliberately asks for the legacy int shape (pos_raw(type=0)).
  * position/tick/deal 'time' is BROKER-clock epoch seconds (CapitalXtend
    UTC+3, measured in b32) — NOT UTC. age_hours is de-rotated for you.
  * envelopes are exactly what the server jsonifies: {ok, data, count} for
    positions/deals/rates, flat {ok, symbol, ask, bid, last, volume, time}
    for the tick, flat {ok, balance, equity, ...} for the account.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# CapitalXtend broker server clock = UTC+3 (measured live, b32/b35).
BROKER_OFFSET_SEC = 3 * 3600

# Field-for-field key sets of the v2 bridge responses. The drift test asserts
# these stay equal to what scripts/mt5_http_server_v2.py actually emits.
POSITION_FIELDS = ('ticket', 'symbol', 'type', 'volume', 'price_open', 'sl',
                   'tp', 'price_current', 'profit', 'swap', 'comment', 'time')
TICK_FIELDS = ('ok', 'symbol', 'ask', 'bid', 'last', 'volume', 'time')
ACCOUNT_FIELDS = ('ok', 'balance', 'equity', 'margin', 'margin_free',
                  'login', 'server', 'currency')
DEAL_FIELDS = ('ticket', 'order', 'position_id', 'entry', 'symbol', 'type',
               'volume', 'price', 'profit', 'swap', 'commission', 'time',
               'comment')
RATE_FIELDS = ('time', 'open', 'high', 'low', 'close', 'tick_volume')
LIST_ENVELOPE_FIELDS = ('ok', 'data', 'count')


def broker_epoch(age_hours: float = 0.0,
                 offset: float = BROKER_OFFSET_SEC,
                 now: datetime | None = None) -> int:
    """Broker-clock stamp for a thing that happened `age_hours` ago (UTC)."""
    now = now or datetime.now(timezone.utc)
    return int((now - timedelta(hours=age_hours)).timestamp()) + int(offset)


def pos_raw(side: str = 'SELL', ticket: int = 99001, entry: float = 4450.0,
            sl: float = 4460.0, tp: float = 4600.0, volume: float = 0.02,
            price_current: float | None = None, profit: float = 0.0,
            swap: float = 0.0, comment: str = '', symbol: str = 'XAUUSD',
            age_hours: float = 0.0, type: object = None,
            broker_offset: float = BROKER_OFFSET_SEC,
            time: int | None = None,
            now: datetime | None = None) -> dict:
    """One item of /api/positions `data`, exactly as the v2 bridge sends it.

    Pass type=0/1 to replay the LEGACY int shape (old C:\\Temp\\bridge.py
    fork); otherwise the string 'BUY'/'SELL' the v2 server produces.
    Pass time=<epoch> to pin an EXACT broker stamp (incident replays);
    otherwise it is derived from age_hours on the broker clock.
    """
    t = type if type is not None else str(side).upper()
    return {
        'ticket': int(ticket),
        'symbol': symbol,
        'type': t,
        'volume': float(volume),
        'price_open': float(entry),
        'sl': float(sl),
        'tp': float(tp),
        'price_current': float(price_current if price_current is not None
                               else entry),
        'profit': float(profit),
        'swap': float(swap),
        'comment': comment,
        'time': int(time) if time is not None \
            else broker_epoch(age_hours, broker_offset, now),
    }


def positions_payload(positions: list | None = None, ok: bool = True) -> dict:
    """The /api/positions envelope: {ok, data, count}."""
    data = list(positions or [])
    return {'ok': ok, 'data': data, 'count': len(data)}


def tick_payload(ask: float = 4600.0, bid: float = 4599.5,
                 symbol: str = 'XAUUSD', last: float = 0.0,
                 volume: int = 0, time: int | None = None,
                 now: datetime | None = None) -> dict:
    """The FLAT /api/tick/<symbol> response (bridge v2 shape)."""
    return {
        'ok': True,
        'symbol': symbol,
        'ask': float(ask),
        'bid': float(bid),
        'last': float(last),
        'volume': int(volume),
        # tick.time is a BROKER-clock epoch (mt5 symbol_info_tick.time)
        'time': int(time if time is not None
                    else broker_epoch(0.0, now=now)),
    }


def account_payload(balance: float = 5000.0, equity: float | None = None,
                    margin: float = 0.0, margin_free: float | None = None,
                    login: int = 10382667, server: str = 'CapitalxtendLLC-MU',
                    currency: str = 'USD') -> dict:
    """The FLAT /api/account response. NOTE: the bridge does NOT send an
    open-position count here — consumers must not invent one (see the
    open_positions finding logged in the backlog)."""
    return {
        'ok': True,
        'balance': float(balance),
        'equity': float(equity if equity is not None else balance),
        'margin': float(margin),
        'margin_free': float(margin_free if margin_free is not None
                             else balance - margin),
        'login': int(login),
        'server': server,
        'currency': currency,
    }


def deal_raw(ticket: int = 98200436, order: int = 103324106,
             position_id: int | None = None, entry: int = 0,
             side: str = 'SELL', volume: float = 0.12, price: float = 4421.3,
             profit: float = 0.0, swap: float = 0.0, commission: float = -0.36,
             symbol: str = 'XAUUSD', comment: str = 'Hermes',
             age_hours: float = 0.0, now: datetime | None = None) -> dict:
    """One item of /api/history/deals `data` (b44: position_id present)."""
    return {
        'ticket': int(ticket),
        'order': int(order),
        'position_id': int(position_id if position_id is not None else order),
        'entry': int(entry),          # 0=IN 1=OUT 2=INOUT
        'symbol': symbol,
        'type': str(side).upper(),    # server maps ORDER_TYPE_BUY→'BUY'
        'volume': float(volume),
        'price': float(price),
        'profit': float(profit),
        'swap': float(swap),
        'commission': float(commission),
        'time': broker_epoch(age_hours, now=now),
        'comment': comment,
    }


def deals_payload(deals: list | None = None) -> dict:
    return {'ok': True, 'data': list(deals or []),
            'count': len(deals or [])}


def rate_row(t: int = 1787000000, open: float = 4600.0, high: float = 4605.0,
             low: float = 4595.0, close: float = 4602.0,
             tick_volume: int = 100) -> dict:
    """One OHLC item of /api/ohlc (and /api/rates) `data`."""
    return {'time': int(t), 'open': float(open), 'high': float(high),
            'low': float(low), 'close': float(close),
            'tick_volume': int(tick_volume)}


def rates_payload(rows: list | None = None, timeframe: str = 'M5') -> dict:
    return {'ok': True, 'data': list(rows or []), 'timeframe': timeframe,
            'count': len(rows or [])}
