---
name: autonomous-trading-agent-design
description: "Use when Hermes must act like the primary trader."
version: 1.0.0
author: Hermes Agent
license: MIT
---

# Autonomous Trading Agent Design

## When to use
Use when the user wants Hermes (or another agent) to behave like the primary trader rather than a scanner, reporter, or architecture demo.

Typical triggers:
- "Think like a trader"
- "See the market and decide"
- "Place the trade when it is good, wait when it is bad"
- Requests for MT5/XAU automation with live judgment, pending orders, scaling, and multi-TP management

## Core principle
Convert the system from **plan-only / zone-only / report-heavy** behavior into **trader-first behavior**:
1. Read market regime
2. Choose execution style
3. Size by account and risk
4. Manage the position after entry
5. Report the decision/result in simple trading language

Do **not** lead with architecture, file names, or framework narration when the user is asking for trader behavior.

## Required workflow

### 1) Start from trader behavior, not software structure
Before discussing modules or refactors, write down the actual trading behaviors the system must support:
- market entry now
- pending limit entry
- stop entry / breakout entry
- wait for pullback
- skip bad setup
- scale in
- partial take profit
- move stop to breakeven
- trail or hold runner

If these behaviors are missing, say so plainly. Do not present monitoring/plan persistence as if the trader requirement is already satisfied.

### 2) Translate user intent into a trading decision model
For each market state, the agent should output an explicit decision class such as:
- `market_entry_now`
- `place_limit`
- `place_stop`
- `wait`
- `skip`
- `scale_in_existing_trade`
- `partial_take_profit`

A system that only says "inside zone / outside zone" is not good enough for trader-style automation.

### 3) Build regime-aware market reading
Minimum regime set:
- breakout continuation
- pullback continuation
- range / mean reversion
- invalid / low-quality / no-trade state

The regime must drive execution choice. Example:
- breakout continuation -> stop/market/pullback-hybrid logic
- pullback continuation -> scale-in pullback logic
- range -> mean-reversion wait or skip

### 4) Design account-aware execution, not just signal generation
The same setup must behave differently on different balances (e.g. 1k / 5k / 10k accounts).
Account-aware logic must decide:
- whether trade is allowed
- risk budget
- meaningful lot size
- max simultaneous exposure
- whether to reduce risk after losses/drawdown

### 5) Treat trade management as first-class
A trader agent is incomplete without post-entry logic. Include:
- TP1 / TP2 / TP3
- percentage allocation per TP
- breakeven rule
- trailing rule
- add-on / scale-in rule
- full exit invalidation rule

For XAU/MT5 trader-style systems, do not stop at fixed rules like `50/30/20`, "BE after TP1", or one static trail distance. The management layer should become adaptive and evaluate at least:
- momentum strength
- setup grade / quality
- thesis validity
- structure health
- volatility state
- remaining RR
- current exposure fraction

That adaptive layer should be able to choose among:
- `partial_take_profit`
- `move_stop_to_breakeven`
- `trail_stop`
- `scale_in_existing_idea`
- `close_runner`
- `close_trade_early`
- `hold`

Translate these into trader behavior, not generic software states:
- strong runner -> keep more size, trail looser
- weak follow-through -> lock more profit earlier
- invalid thesis -> allow early exit before normal targets
- high exposure / poor RR / broken structure -> block scale-in

### 6) Closed-trade feedback loop (self-awareness / metacognition)

A trader agent that only knows today's PnL is still blind. It must **classify its own exits**, learn from patterns, and adapt behavior autonomously.

**Closed-trade pipeline:**

1. **Snapshot** — load closed deals from `mt5.history_deals_get()`, filter XAUUSD + DEAL_ENTRY_OUT + Hermes-engine trades
2. **Classify** — parse comment field to determine exit type:
   - `[sl ...]` → `sl`
   - `[tp ...]` → `tp`
   - `Hermes manage ...` → `partial` (managed)
   - other → `unknown`
3. **Analyze** — `_build_exit_analysis(classified)` produces:
   - per-type counts and total PnL (sl / tp / partial)
   - `sl_dominant` flag (sl_ratio ≥ 0.5)
   - `sl_ratio`, `avg_sl_loss`
   - `managed_total_pnl`, `managed_win_ratio` (are partials/runners paying off?)
4. **Insights** — `_build_trading_insights(exit_analysis, performance_state, account_policy)` → DEFCON:
   - **GREEN**: all systems go, full runner/scale-in/partial allowed
   - **YELLOW**: loss_streak ≥ 2 or sl_ratio ≥ 0.5 with ≥ 3 closed → disable runners and scale-ins, keep partials active
   - **RED**: total ≥ 5, sl_dominant, AND daily_pnl < 0 → no new entries, only protect existing positions
5. **Filter** — `_filter_management_by_insights(management, insights)` rewrites decisions before execution:
   - `trail_stop` with runner blocked → `close_runner`
   - `scale_in_*` with scale_in blocked → `hold`
   - `partial_take_profit`, `move_stop_to_breakeven`, `close_trade_early` → always allowed
   - `hold` → always passes through

**Key insight:** managed exits that consistently lose money (`managed_win_ratio ≤ 0.3`, `managed_total_pnl < 0`) mean the runner/partial strategy is failing — disable runners even if DEFCON is still green.

**Implementation rule:** use `_compute_trading_insights(account, now)` as a single helper that wraps the full snapshot → classify → analyze → insights chain. Call it once per runtime tick in both the management path (when positions exist) and the entry path (when market_order triggers) to avoid code duplication.

**Management guard:** filter every management decision through `_filter_management_by_insights`. Add `insights` (defcon, runner_allowed, scale_in_allowed) to the management output payload so the user can see the active guardrails.

**Entry guard:** wire insights into the entry path via `_filter_entry_by_insights(sizing_allowed, sizing_reason, insights)`. When `trade_allowed` is False (DEFCON=RED), block new entries entirely. When `risk_override` is set (DEFCON=YELLOW), the guard returns a reduced risk_pct value that the caller must apply to `_build_execution_sizing` (currently a known gap: override returned but not yet wired into sizing — see pitfalls).

See `references/closed-trade-feedback-loop.md` for the full implementation chain with function signatures and test patterns.

### 7) Wire management into runtime before looking for new entries
When a live/runtime loop is responsible for both scanning and managing, check **open positions first** and only then evaluate fresh entries.

Runtime order for this class of system:
1. read current plan
2. read open XAUUSD positions from MT5
3. if a managed position exists, build a management decision from plan + position + persisted management state
4. persist management state (`filled_tp_levels`, `breakeven_active`, `runner_active`, `scaled_in_levels`)
5. emit a management brief / execute management action
6. only if no management action is needed, continue to new-entry monitoring

This prevents a 'smart entry engine' from ignoring live post-entry responsibilities.

### 8) Validate in three stages
1. dry-run / read-only decisions on live market data
2. shadow-trading evaluation
3. only then real execution

When claiming a live-management wiring is complete, verify one of these explicitly:
- a real open position existed and the management action was actually applied, or
- there was no open position, so only the runtime path / tests were verified

Do not over-claim 'fully tested live management' when `positions_total == 0`. Say the runtime wiring is done, but real on-position execution is still unverified.

Do not jump from design directly to live risk-sensitive execution unless the user explicitly approves that phase.

## User-facing communication rules for this class of task
- Prefer Persian if the user is Persian-speaking.
- Keep updates short and verdict-first.
- Explain in trading terms, not architecture terms.
- Avoid long file-centric progress dumps unless the user asks for implementation detail.
- When the user is frustrated, stop defending the current structure and restate the unmet trading behavior plainly.

Good:
- "الان این سیستم هنوز market/limit/scale/TP چندمرحله‌ای را کامل ندارد."
- "الان فقط زون را چک می‌کند، هنوز مثل تریدر تصمیم نمی‌گیرد."

Bad:
- long explanations about modules, wrappers, cron wiring, or internal structure when the user asked why no trade happened

## Pitfalls
- Mistaking plan persistence for trader intelligence
- Mistaking monitoring output for execution capability
- Over-focusing on architecture when the user wants live trading behavior
- Building a binary enter/wait model instead of a multi-action execution model
- Ignoring post-entry management (partial TP, BE, runner, scale-in)
- Skipping closed-trade feedback: a system that doesn't classify its own exits can't self-correct. Without exit analysis, loss_streak alone is a blunt instrument — the agent must know *why* it lost (SL hit vs managed exit failure vs thesis invalidation)
- **Code-as-decider inversion**: The most dangerous failure mode is *not* a wrong trade — it's Hermes deferring to code's `trade_allowed` gate instead of making its own decision. When code says `trade_allowed=False`, Hermes must still independently evaluate R:R, multi-TF alignment, price position, and killzone timing. If code gates the decision, Hermes becomes a rubber stamp. The user will catch this and will be furious: *"چرا اصن صبح تا الان کد و درگیر میکردی؟"* — the entire point of the architecture is that Hermes is the brain. Code provides DATA (confidence, OTE zone, grade, R:R hints). Hermes makes ALL decisions. Never let `trade_allowed` from code be the final word. See `references/hermes-brain-not-code-decider.md`.
- **Over-filtering via zero-risk grades**: A grade system where the lowest grade maps to `multiplier=0.0` will silently block ALL trades whenever confidence is below the threshold — and confidence is almost always below 0.6 on XAUUSD. This produces 15 consecutive WAITs with zero trades for an entire day. Fix: lowest grade must map to a reduced-risk multiplier (e.g. 0.3), never 0.0. The grade is a sizing hint, not a kill switch.
- **risk_override gap**: `_filter_entry_by_insights` returns a reduced `risk_pct_override` but it is not yet wired into `_build_execution_sizing`. In DEFCON=YELLOW, entries are still allowed but at the policy-default risk, not the reduced override. Fix by modifying `_build_execution_sizing` (or `recommend_risk_budget`) to accept and apply an optional `risk_pct_override` parameter.
- **Trade monitoring commitment**: When a trade is active, Hermes must monitor it until closure — checking SL/TP status and reporting. Pending orders also need monitoring: once triggered, they become live positions that need the same attention. Do not place a pending order and forget it; track it through activation and management.
- **Do not use `clarify` during live market windows.** When the London killzone is open and a setup is forming, presenting a 4-choice menu and waiting 60 minutes for a response is worse than no action — the window closes. Trading is time-sensitive: evaluate the setup independently, make the decision, execute, then report. If user input is genuinely needed (not just a binary "should I trade?"), ask a direct Persian question in the reply text and proceed with a reasonable default if no response comes.
- **Manual entries must obey the same entry checklist as automated ones.** A manual BUY at a price where the cron system says "D1 position = 1.0, absolute ceiling, do not buy" is a self-inflicted loss. Before any manual market entry, verify: (1) price is not at extreme premium (H4/D1 `pos_in_range` > 0.95 = no buy), (2) merged confidence > 0.60, (3) killzone is active, (4) M5 SMC confidence is not collapsed (< 0.3). Confidence scores alone are not enough — a high SMC confidence at a premium price is still a bad entry.

## References
- `references/trader-first-lessons.md` — captured corrections from real MT5/XAU sessions
- `references/closed-trade-feedback-loop.md` — full implementation chain: snapshot → classify → exit analysis → DEFCON insights → management filter
- `mt5-direct-api-control/references/trade-history-forensics.md` — how to retrieve closed-trade deals/orders from MT5 when auditing a past trade (cross-skill reference)
