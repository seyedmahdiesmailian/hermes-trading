---
name: account-aware-trading-risk
description: Use when designing account-aware trading risk and sizing.
---

# Account-Aware Trading Risk

Use when designing, auditing, or implementing automated trading risk and position-sizing logic for MT5 or similar broker-connected systems, especially when the same strategy must support multiple account sizes safely.

## Core principles

1. **Design risk policy before wiring execution**
   - If the user asks for logic, policy, sizing, or framework design, do **not** jump straight to live runtime execution.
   - Separate:
     - **policy/design work**
     - **implementation work**
     - **live execution / live verification**
   - Only run live trading/runtime paths when the user explicitly asks for execution or live verification.

2. **Account-aware, not fixed-lot**
   - Never hardcode one lot size for all accounts.
   - Size from account state plus setup quality:
     - balance
     - equity
     - free margin / margin health
     - open-position count
     - stop distance
     - symbol constraints (min/step/max volume)
     - setup grade / market quality

3. **Profitability over cosmetics**
   - For trading automation work, prioritize edge, execution quality, and risk discipline over message formatting or cosmetic reporting.
   - Reporting improvements are secondary unless the user explicitly requests them.

4. **Avoid both failure modes**
   - Do not make filters so strict that the system undertrades and misses good setups.
   - Do not allow tiny, economically meaningless trades just because the broker minimum size is available.
   - Target **selective but active** behavior.

## Recommended framework

### 1) Survival rules
Block new trades when account health is impaired, e.g.:
- daily drawdown beyond limit
- dangerous floating drawdown
- poor margin health
- loss streak beyond policy threshold
- position limit already reached

### 2) Regime classification
Classify the account into a regime before sizing:
- **normal**
- **defensive**
- **recovery**
- **locked**

Regime should affect whether trading is allowed and how much risk budget is available.

### 3) Setup grading
Grade setups rather than using only yes/no:
- A = full allowed risk
- B = reduced risk
- C = no trade

Grade from market structure quality, alignment, trigger quality, and execution quality.

### 4) Risk budget
Compute a per-trade risk budget from:
- account tier / balance band
- regime multiplier
- setup grade multiplier

### 5) Position sizing
Use:
- risk budget in USD
- stop-loss distance
- per-symbol point value economics
- broker volume constraints

Then reject trades that are not economically meaningful for that account.

## Practical rules of thumb

- Default to **single-position discipline** until the strategy proves stable.
- A broker minimum lot is **not** proof the trade is worth taking.
- Require both:
  - risk to be controlled
  - reward / payoff to be meaningful for the account
- When the user asks for policy examples like “for a 1000 USD account maybe 0.05 lot”, treat that as a design target to evaluate technically, not as a hardcoded rule to blindly force.

## Workflow

1. Read the user's real goal: design vs implementation vs live execution.
2. Build or revise the account policy model.
3. Build sizing logic from risk budget, stop distance, and symbol constraints.
4. Add tests for multiple account sizes and degraded account states.
5. Verify with non-trading checks first.
6. Only then wire into live runtime if the user explicitly wants execution.

## Pitfalls

- **Pitfall: jumping to live runtime after a policy request**
  - If the user asked for a framework or logic, stay design-first until they explicitly approve implementation/execution.

- **Pitfall: over-filtering**
  - Do not keep stacking gates until the system stops trading entirely.
  - Preserve executable pathways for good-enough high-quality setups.

- **Pitfall: meaningless tiny trades**
  - Do not place token-size trades that cannot materially help the account.
  - Enforce a minimum meaningful trade threshold beyond broker minimums.

- **Pitfall: one-account overfitting**
  - Do not tune logic so tightly around one current account that it fails on the next connected account.

## Support files

- See `references/session-lessons.md` for condensed lessons from a real MT5/XAU automation session that drove these guardrails.
