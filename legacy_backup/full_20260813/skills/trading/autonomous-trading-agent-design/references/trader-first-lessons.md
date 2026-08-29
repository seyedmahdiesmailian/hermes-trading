# Trader-first MT5/XAU lessons from this session

## User expectation that must override architecture drift
When the user says Hermes should be the trader, they mean:
- read the market now
- decide whether to enter now, place pending orders, or wait
- size by account
- manage the position after entry
- report the trade/result simply

Do not treat plan persistence, monitoring cadence, cron polish, or reporting cleanup as evidence that this requirement is satisfied.

## Correction captured
The user explicitly rejected repeated architecture-heavy explanations and wanted trader behavior first. In this class of task, respond by:
1. admitting the missing trader behaviors plainly
2. naming the missing execution/management capabilities
3. moving immediately into regime, execution, and management logic

## Durable design lessons
- A binary `inside_zone / outside_zone` model is too weak for trader-style automation.
- The minimum execution action set should include: market now, limit, stop, wait, skip, scale-in, partial-take-profit.
- Regime classification should distinguish at least: breakout continuation, pullback continuation, range.
- Account-aware logic must be separated from signal quality but consumed by the final execution gate.
- Dry-run and shadow-trading should come before any live risk-sensitive rollout.

## Language / communication lesson
For this class of work, prefer short Persian verdicts in trading language over architectural narration. When the user asks why no trade happened, answer in terms of market state and missing trader capability first, not internal modules.
