---
name: mt5-direct-api-control
description: "Use when controlling MT5 directly via Python API."
created_by: agent
---

# MT5 Direct API Control

## Trigger
Use when Hermes should control a MetaTrader 5 terminal directly through the Python `MetaTrader5` package instead of MQL file bridges, command files, or status files.

Especially use this when:
- file-based bridges are ambiguous, stale, or hardcoded
- exact lot size, symbol, SL/TP, and open-position state must be verified directly
- the user wants faster, cleaner, direct control
- cron monitoring or trading should operate from direct API reads

## Core Principle
Prefer **direct MT5 API control** over `HermesCommand.txt` / `HermesStatus.txt` bridges whenever direct Python access is available and initialized successfully.

Direct API control is better because it gives:
- exact live account state
- exact open positions and volumes
- direct symbol discovery
- `order_check` before real execution
- exact order placement/closure without bridge lag or chart-EA ambiguity

## Workflow
1. **Initialize direct API first**
   - Use Python `MetaTrader5`.
   - Confirm `mt5.initialize()` returns true.
   - Read `account_info()` immediately to verify the terminal/account is reachable.

2. **Use direct status as source of truth**
   - Balance, equity, margin, positions, and symbols-with-positions should come from API results, not sidecar text files.

3. **Discover market coverage directly**
   - Read `symbols_get()` / `symbols_total()` to see what the broker actually exposes.
   - Select symbols explicitly before checks/orders.

4. **Always run `order_check` before `order_send`**
   - Validate symbol, lot size, margin impact, SL/TP placement, and broker acceptance first.
   - If `order_check` is not clean, do not send the trade.

5. **Use dynamic sizing**
   - Never hardcode lot size inside the execution path.
   - Normalize requested volume against broker min/max/step for the symbol.
   - Keep sizing conservative by default and adapt per setup quality and account state.

6. **Keep cron output short**
   - For recurring reports, output should be compact and decision-oriented.
   - Prefer very short bullets: account state, strongest symbol, likely direction, short reason, action/no-action.

## Recommended Command Surface
Keep a reusable Python controller script that supports at least:
- `status`
- `symbols`
- `check SYMBOL BUY|SELL LOT SL TP`
- `open SYMBOL BUY|SELL LOT SL TP "comment"`
- `close SYMBOL`
- `pending SYMBOL KIND PRICE LOT SL TP "comment"` — place pending orders (KIND: BUY_STOP|SELL_STOP|BUY_LIMIT|SELL_LIMIT)
- `cancel_order TICKET` — cancel a pending order by ticket
- `orders SYMBOL` — list pending orders for a symbol

Pending orders are essential for cron-based trading: they let Hermes pre-position entries at key levels between 15-minute wake cycles so opportunities don't evaporate before the next tick. See `references/pending-orders-and-presession-fixes.md` for MT5 order type constants and verified CLI examples.

This creates one direct, auditable control plane for both manual sessions and cron jobs.

## Analysis Standard for Trading Decisions

When using direct MT5 control for trading, evaluate setups with multi-factor confluence rather than single-signal entries.

Two analysis frameworks are now available:

**Classic (mt5_xau_context.py)**: HTF/LTF market structure, momentum, value zones, regime, alignment.

**SMC/ICT/RTM (mt5_xau_smc.py)**: Order Blocks, Fair Value Gaps, Liquidity Sweeps, Market Structure (BOS/CHoCH), Premium/Discount, Killzone timing, POI grading.

Both are merged via `merge_smc_with_classic()` into a weighted consensus. When classic is neutral, SMC dominates. When they agree, confidence is boosted. When they conflict, signals are dampened.

Factors evaluated: reward-to-risk, account state, position sizing, killzone timing, pullback quality, breakout quality, sweep/fake-breakout behavior.

Prefer **no trade** over weak trade.

## Reporting Style
For recurring cron or watchlist outputs:
- keep it short
- avoid long essays
- highlight only the strongest actionable conclusion
- say clearly whether a trade was taken or skipped

## Pitfalls
- **Do not trust a bridge-era cron prompt after migration.** Updating the script alone is not enough; update the cron prompt too so future runs stop mentioning file-based control.
- **Do not trust a bridge-era test unless the position volume was read back directly from MT5.** If a user says a test still opened at 0.1, verify from direct API position data rather than assuming the new path executed.
- **Do not leave fallback paths active once the user asks for direct-only control.** Remove or decommission bridge artifacts so stale reports cannot keep referencing old behavior.
- **Do not treat historical cron output as current configuration.** Old delivered messages may still mention the legacy method even after the job has been migrated.
- **Never let a `check` path place live trades.** Validation helpers must stop at `order_check`; if shared helper code also calls `order_send`, a supposedly safe test command can open real positions.
- **Do not assume FX stop placement rules transfer to indices/CFDs.** Some symbols accept the market order but reject inline SL/TP with `Invalid stops`; use the class-specific fallback in `references/indices-cfds-stop-handling.md`.
- **CLI has no history command.** When the user asks "what happened with that trade?", `mt5_direct.py` only shows live positions/orders — not closed deals. Use raw `history_deals_get()` / `history_orders_get()` to reconstruct the full trade lifecycle. See `references/trade-history-forensics.md`.
- **Manual entries must follow the same discipline as automated ones.** If the cron system's analysis says "price at absolute ceiling, do not buy," a manual market entry at that same price is the same mistake. Always check premium position (H4/D1 `pos_in_range`) and OTE distance before any manual entry — not just confidence scores.
- **Manual override is the #1 cause of trading discipline failures.** When investigating losses, check if trades were placed manually against system recommendations. Look for heartbeat mode changes (`hermes_degraded` → `hermes_active`) and timeline gaps between cron WAIT decisions and actual trade execution times. The issue is usually discipline, not code.

## Asset-Class Execution Note
For non-FX symbols such as indices/CFDs:
- first validate the normal request with inline stops
- if stop placement is rejected but the symbol otherwise validates, retry the check without inline stops
- send the market order only after a clean `order_check`
- then attach SL/TP with `TRADE_ACTION_SLTP`
- verify the final live position and attached stops directly from MT5

This keeps execution direct while adapting to broker-specific symbol behavior.

## Support Files
- `scripts/mt5_direct_controller.py` — template direct-controller script shape for future reuse.
- `references/cron-report-shape.md` — compact recurring-report format for this class of trading job.
- `references/trade-history-forensics.md` — retrieving closed-trade history via raw `history_deals_get` / `history_orders_get` (no CLI command exists).
