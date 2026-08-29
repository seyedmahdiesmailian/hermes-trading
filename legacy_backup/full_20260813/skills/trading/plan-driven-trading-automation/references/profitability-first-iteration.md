# Profitability-First Iteration for Plan-Driven XAU Automation

Use this note once the runtime is already operational and reporting is readable enough. The next iterations should optimize trading quality, not cosmetics.

## User preference signal

For this class of task, the user explicitly prioritizes:
- profitability
- quality of real trading output
- stronger analysis and trigger logic

And explicitly de-prioritizes:
- message cosmetics
- extra formatting churn
- non-essential reporting polish

## Recommended improvement order

1. **Harden bias classification**
   - Do not label bias bullish/bearish from a tiny net move alone.
   - Require meaningful net movement plus enough same-direction closes.
   - Let choppy or low-energy sequences resolve to `neutral`.

2. **Expose quality signals in context**
   Add reusable plan-context fields that later stages can gate on, such as:
   - multi-timeframe bias votes
   - alignment label (`aligned`, `mixed`, `neutral`)
   - trend strength
   - ATR-normalized distance to value/entry zones

3. **Add execution quality gates**
   Zone-touch plus trigger confirmation is not enough.
   Before allowing `market_order`, require structural quality such as:
   - aligned multi-timeframe bias
   - minimum trend-strength threshold

   If these fail, downgrade to a wait state with an explicit machine reason like `quality_filter` instead of promoting the trade anyway.

4. **Prioritize next research/engineering work on edge, not formatting**
   After the above, direct effort into:
   - rejection quality
   - continuation quality
   - close-location logic
   - impulse vs pullback distinction
   - sweep/reclaim confirmations
   - better post-entry management

## Practical lesson from this session

A working plan-driven runtime can still be too permissive if execution depends mainly on:
- price reaching a zone
- a basic trigger flag

A better pattern is:
- context computes structural quality
- orchestrator/runtime blocks weak structures
- only strong aligned setups can escalate to execution
