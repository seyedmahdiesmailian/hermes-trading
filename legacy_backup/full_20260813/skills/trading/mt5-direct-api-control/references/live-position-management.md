# Live MT5 position management via direct Python API

Use this when Hermes must manage an already-open MT5 position directly through Python rather than only opening/closing whole symbols.

## Verified workflow
1. Read the live position with `positions_get()` and treat ticket, volume, SL, and TP as the source of truth.
2. For **partial close**, send a `TRADE_ACTION_DEAL` in the opposite direction with the `position` field set to the open ticket and the close volume normalized to broker step/min.
3. For **SL/TP modification** (breakeven or trailing), send `TRADE_ACTION_SLTP` against the exact position ticket using absolute price levels.
4. For **scale-in**, place a new market order as a separate leg; verify the new leg with `positions_get()` and manage it independently if needed.
5. After every management action, re-read positions from MT5 to verify the new volume/SL/TP instead of trusting retcode alone.

## Pitfalls
- Partial close is not `TRADE_ACTION_SLTP`; it is an opposite-side market deal linked to the existing `position` ticket.
- Invalid-stop errors on trailing/breakeven usually mean the requested SL is on the wrong side of the current market or too close to price; choose a still-valid protective level.
- When clearing or intentionally omitting TP during an SLTP update, pass explicit absolute values (`0.0` when clearing) rather than truthy/falsy shorthand.
- Scale-in legs can appear as separate open positions/comments; do not assume the parent ticket absorbs them automatically.

## Session-proven checks
- Verify partial close by confirming volume decreased on the original ticket or that the targeted leg disappeared.
- Verify SL modification by reading back the exact `sl` field from `positions_get()`.
- If a scale-in leg is opened for testing, explicitly close that leg afterward rather than assuming symbol-level cleanup already happened.
