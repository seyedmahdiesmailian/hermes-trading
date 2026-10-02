# Retrieving Closed-Trade History from MT5 Direct API

Use when the user asks "what happened with that trade?" or you need to audit closed positions, stop-loss events, or partial fills.

## The Gap

The `mt5_direct.py` CLI supports: `status`, `open`, `close`, `check`, `pending`, `cancel_order`, `orders`, `symbols`.

There is **no `history` command**. To retrieve closed deals and orders, use raw Python via `execute_code` or a script.

## Verified Method

```python
import MetaTrader5 as mt5
from datetime import datetime

mt5.initialize()

from_d = datetime(2026, 8, 9)
to_d   = datetime(2026, 8, 11, 10, 0)

# 1. DEALS — actual fills (entries, exits, SL/TP hits)
deals = mt5.history_deals_get(from_d, to_d)
for d in deals:
    # type: 0=BUY, 1=SELL
    # entry: 0=ENTRY_IN, 1=ENTRY_OUT, 2=ENTRY_INOUT
    # reason: 3=CLIENT/EXPERT, 4=SL, 5=TP, ...
    print(f"ticket={d.ticket} order={d.order} symbol={d.symbol} "
          f"type={d.type} entry={d.entry} vol={d.volume} "
          f"price={d.price} profit={d.profit} comment={d.comment}")

# 2. ORDERS — the full order lifecycle (pending → filled/canceled/expired)
orders = mt5.history_orders_get(from_d, to_d)
for o in orders:
    # type: 0=BUY, 1=SELL, 2=BUY_LIMIT, 3=SELL_LIMIT, 4=BUY_STOP, 5=SELL_STOP
    # state: 0=STARTED, 1=PLACED, 2=CANCELED, 3=PARTIAL, 4=FILLED, 5=REJECTED, 6=EXPIRED
    print(f"ticket={o.ticket} type={o.type} state={o.state} "
          f"price_open={o.price_open} sl={o.sl} tp={o.tp} "
          f"comment={o.comment}")

mt5.shutdown()
```

## Key Fields for Forensics

| Field | What it tells you |
|-------|-------------------|
| `deal.comment` | Contains `[sl 4414.00]` for SL hits, `[tp ...]` for TP hits, or custom comment like `Hermes FVG` |
| `deal.entry` | 0 = position opened, 1 = position closed, 2 = inout |
| `deal.reason` | 3 = client/expert initiated, 4 = SL triggered, 5 = TP triggered |
| `order.state` | 4 = FILLED (the order executed), 2 = CANCELED, 6 = EXPIRED |
| `order.type` | 2=BUY_LIMIT, 3=SELL_LIMIT, 4=BUY_STOP, 5=SELL_STOP, 0=BUY(market), 1=SELL(market) |

## Common Patterns

**Pending order → SL hit:**
- Order type 2 (BUY_LIMIT), state 4 (FILLED) → the limit was triggered
- Followed by a deal with entry=0 (open), then a deal with entry=1 (close), comment `[sl ...]`, profit negative

**Verifying a trade was stopped out:**
- Look for deal with `entry=1` (close) and `comment` starting with `[sl`
- The `profit` field shows the actual P&L
- The `position_id` links the entry and exit deals

## Pitfalls
- `TradeDeal` object has `order` (not `order_id`) — using `d.order_id` raises AttributeError.
- `history_deals_get` requires datetime range, not just a count.
- Deals include commission as a separate field (`d.commission`), not rolled into `profit`.
- An entry deal has `profit=0.0`; only the exit deal shows realized P&L.
