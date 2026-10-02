# Indices/CFDs direct MT5 execution notes

Use this when direct Python `MetaTrader5` control works for FX but some index/CFD symbols reject the same open-order pattern.

## Durable lessons from live execution

### 1) `check` must never send a real order
A validation helper must only run `order_check`. Do **not** reuse a helper that falls through to `order_send`, or a supposedly safe `check` command can open live positions.

### 2) Some indices/CFDs reject inline SL/TP on market open
Observed pattern on symbols like `DJIUSD`:
- `order_check` with inline `sl`/`tp` can return `Invalid stops`
- the same symbol can still accept a market order **without** inline stops
- after the fill, `TRADE_ACTION_SLTP` can successfully attach SL/TP to the live position

Reliable sequence:
1. Build the normal market-order request with symbol-aware price/volume normalization.
2. Try `order_check` with inline stops.
3. If validation fails specifically on stop placement but the symbol otherwise trades, retry validation with stops removed.
4. If the stopless request validates, send the market order.
5. Immediately follow with `TRADE_ACTION_SLTP` to attach the intended SL/TP using current symbol point/digits.
6. Verify the resulting position directly from `positions_get()`.

### 3) Filling mode and stop handling should be probed separately
For symbols that behave differently from FX:
- test candidate filling modes explicitly (`IOC`, then broker-allowed alternatives)
- vary **one dimension at a time**: first stops on/off, then filling mode
- keep an attempts log so you can explain why the final request shape was chosen

### 4) Style/workflow preference for this trading class
When reporting automated MT5 activity for this user:
- keep recurring cron output very short
- analysis can be deep internally, but the delivery should be compressed to a few bullets
- compare several liquid markets before acting; do not give a shallow single-symbol read

## Practical implication
For multi-asset MT5 automation, separate execution logic by asset class:
- FX/metals may accept inline SL/TP directly
- indices/CFDs may require open-first, then `TRADE_ACTION_SLTP`
- always confirm the actual filled position and attached stops via direct API reads, not assumptions
