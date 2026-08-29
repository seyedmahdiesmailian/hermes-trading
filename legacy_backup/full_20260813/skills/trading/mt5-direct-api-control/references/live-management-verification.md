# Live MT5 Management Verification

Use this when extending MT5 direct API control from entry execution into post-entry management.

## Verified pattern
1. Open a very small demo position only after a clean `order_check`.
2. Read the live position back with `positions_get(symbol=...)` and capture ticket, volume, entry, SL, and TP.
3. Verify stop modification with `TRADE_ACTION_SLTP` using absolute prices.
4. Verify partial close with an opposite-side `TRADE_ACTION_DEAL` request that includes the existing `position` ticket.
5. Read the live position again and confirm:
   - SL changed to the requested price
   - volume decreased by the expected amount
6. Only after read-back confirmation should runtime state mark TP-filled / breakeven-active.

## Durable implementation notes
- Partial close of a BUY position must send a SELL deal; partial close of a SELL must send a BUY deal.
- Build management request objects separately before sending them so they can be unit-tested without touching MT5:
  - `build_partial_close_request(...)`
  - `build_modify_position_price_request(...)`
- Execution helpers should return the raw request plus MT5 result payload for later verification.
- Runtime state should update only after the live execution path returns success.

## Minimal demo verification recipe
A quick end-to-end proof for the management layer is:
- open a tiny XAUUSD demo position
- move SL to a breakeven-style price with `TRADE_ACTION_SLTP`
- partial close a small fraction of volume
- confirm updated SL and reduced volume via `positions_get`

This is enough to prove the live management execution layer works before adding full trailing / runner orchestration.