# Session Lessons: MT5/XAU Account-Aware Risk

## Why this skill was created
A real MT5/XAU automation session exposed two recurring failure modes:

1. **Over-filtering / undertrading**
   - The user explicitly did not want a system that keeps rejecting everything and missing real opportunities.
   - The lesson is to tune for **selective but active**, not just stricter gating.

2. **Economically meaningless tiny trades**
   - The user explicitly rejected token-size entries that do not materially grow the account.
   - Broker minimum size is not enough; the trade must also be worth taking for the account.

## Workflow correction learned from the user
The user corrected the workflow: when asked for technical design and overall logic, do not jump directly to runtime/live execution. First build the model and policy, then implement, and only run live paths when explicitly requested.

## Concrete framework pieces that proved valuable
- account regime classification: `normal`, `defensive`, `recovery`, `locked`
- setup-grade-aware risk budgeting: `A`, `B`, `C`
- single-position discipline as the starting default
- meaningful-size rejection beyond broker minimum lot
- tests that compare behavior across several account balances instead of a single current account

## Example design target from the session
The user gave a concrete example: for roughly a 1000 USD account, a trade around `0.05 lot` may be a more meaningful target than `0.01 lot`, depending on stop distance and total risk budget. Treat this as a design calibration example, not a hardcoded constant.

## Guidance for future sessions
If the user emphasizes profitability and output quality over message formatting, spend effort first on:
- risk policy
- sizing quality
- trigger quality
- setup quality
- drawdown discipline

Only spend time on reporting/cosmetics when specifically requested.
