---
name: forex-automated-trading
description: Bridge MetaTrader to Hermes for automated trading via files.
---
# forex-automated-trading
Use for MetaTrader 4/5 automated trading via Hermes file-based command bridge.

## Triggers
- Trading/investing in Forex, Crypto, or Gold via MetaTrader.
- Deploying algorithmic trading strategies (EA) managed by Hermes.

## Workflow
1. Create/Update EA: Use the `HermesTrade.mq5` template to establish a bridge between MetaTrader and Hermes.
2. File Bridge: Hermes writes `BUY`/`SELL` commands to `.../MQL5/Files/HermesCommand.txt`.
3. Execution: The EA reads the file via `OnTimer()` or `OnTick()`, executes the trade, and deletes the command file.
4. Risk Management: Always embed SL/TP logic and balance/margin checks in the EA or the command logic before execution.

## Pitfalls
- **File Encoding:** Always use `FILE_ANSI` when reading/writing command files to avoid garbled Unicode characters (e.g., `啂ਖ਼`).
- **Pathing:** Avoid `FILE_COMMON` if the EA struggles to access public paths; prefer the local `AppData` terminal path for reliability.
- **Timing:** Use `EventSetTimer(1)` in `OnInit()` for frequent, non-blocking command polling.
- **State:** Ensure `Auto Trading` (Algo Trading) is enabled in the MetaTrader UI (green status) before deploying.

## References
- `scripts/hermes_trade_ea.mq5` (A reliable template with timer-based execution).