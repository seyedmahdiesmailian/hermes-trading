---
name: plan-driven-trading-automation
description: "Use when MT5/XAU automation should be plan-first and quiet."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [trading, mt5, xauusd, automation, plan-driven, reporting, cron]
---

# Plan-Driven Trading Automation

Use when building, migrating, or operating MT5 automation for XAUUSD in a professional **plan-first** style instead of a noisy scan/re-score loop.

## Trigger

Use for tasks where the user wants:
- MT5 direct automation for XAUUSD
- a morning/session plan with zones, invalidation, and target structure
- conditional execution only when price reaches the planned zone
- quiet monitoring and meaningful reports instead of frequent scanner-like pings
- concise build/progress updates during implementation work

## Core Operating Model

1. **Build the plan first — now dual-analysis**
   - Classic analysis (`mt5_xau_context.py`): value zones, regime, bias from M15/H1/H4 closes.
   - SMC/ICT/RTM analysis (`mt5_xau_smc.py`): Order Blocks, Fair Value Gaps, Liquidity Sweeps, Market Structure (BOS/CHoCH), Premium/Discount zones, Killzone timing, POI grading.
   - **Merge** via `merge_smc_with_classic()`: weighted consensus — SMC gets dominant weight when classic is neutral; agreement boosts, disagreement dampens.
   - Persist the active plan with both classic and SMC fields so later runs continue from the same thesis.

2. **Monitor against the plan, not from scratch**
   - Later runs compare live price to the stored plan.
   - Avoid full analysis/re-scoring on every cron tick unless the plan expired or reassessment time arrived.

3. **Execute only on planned conditions**
   - The code should be an execution/state engine, not the primary analyst.
   - Only trigger direct MT5 execution when the stored plan allows it.
   - Hermes acts as **overseer**: can override plans, fix bugs, adjust risk, and supervise execution — but the code runs autonomously on cron.

4. **Keep reporting quiet**
   - Prefer silent-unless-meaningful-change behavior.
   - Emit reports for: new plan, reassessment, zone change, trigger confirmation, order placed, invalidation, or other meaningful state transition.
   - If nothing meaningful changed, emit nothing.

## SMC/ICT/RTM Analysis Layer

The `mt5_xau_smc.py` engine provides 16 institutional-grade concepts (7 basic + 9 advanced since 2026-08-08):

**Basic (v1):** Order Blocks, FVG, Liquidity Sweep, Market Structure (BOS/CHoCH), Premium/Discount, Killzone Timing, POI Grading.

**Advanced (v2):** Breaker Block, Rejection Block, OTE Zone (0.62-0.79 fib), Power of 3, Turtle Soup, Silver Bullet (10-11AM/2-3PM NY), Session Liquidity, Volume Imbalance.

See `references/smc-architecture.md` for merge flow, killzone sessions, and TDD pitfalls. See `mt5-forex-automation` → `references/smc-ict-rtm-engine.md` for full function table.

**Overseer role** (Hermes):
- SMC code runs autonomously every 15min on cron
- Hermes monitors: can inspect live analysis, override plans, fix bugs
- Pattern: cron → runtime (classic + SMC + merge → plan → execution) + Hermes supervision
- **Review loop is part of the deliverable, not optional**: the user expects each plan/analysis to also reach Hermes for quality review (compare SMC output vs price reality, flag bad theses, tune parameters). When building or extending this system, always wire the analysis snapshot → Hermes review path — do not stop at "code runs autonomously". The user explicitly called out a dropped overseer layer as a broken promise (2026-08-08).
- **Concrete implementation** (see `references/oversight-layer.md`):
  - `mt5_xau_review.py` — save/load/format review snapshots from the runtime
  - Wired into `mt5_xau_runtime.py` at `_build_live_plan` after `_save_plan_and_state`
  - Separate review cron (every 2h, `terminal` + `file` toolsets only) reads latest snapshot and sends Persian quality report
  - Snapshot stored at `trading/xau_plan/review_snapshots/latest_snapshot.json`
  - **Cron debugging**: if the review cron fails with provider errors, check OmniRoute combo models via `curl http://localhost:20128/api/v1/combos` (no auth needed) — dead providers (e.g. nvidia's EOL'd deepseek-v4-pro) may require combo update or cron recreation

## User Workflow Preferences For This Class Of Task

- Prefer **analysis-first by the agent, execution/state by code**.
- Do **not** drift back into a rule-jungle scanner that re-decides everything every few minutes.
- Prefer **fewer, higher-quality, plan-based trade opportunities** over frequent rescoring/chasing.
- Runtime/user-facing reporting should be **Persian, concise, and scan-friendly**.
- During implementation work, avoid long promise-heavy chatter. Do the work first, then report only **tool-verified progress**.
- Progress updates should use short checkpoint sections when relevant:
  - Done
  - Files
  - Tests
  - Live verify
  - Blockers

## Implementation Guidance

- Keep direct MT5 API as the execution path when available.
- Separate responsibilities:
  - context/analysis inputs
  - plan construction
  - storage/state
  - orchestrator/runtime
  - reporting
  - execution adapter
- Persist at least:
  - current active plan
  - runtime state
  - execution log
  - reassessment log
- Favor wrappers/runtimes that can run silently on no-change so cron output remains meaningful.

## Reporting Guidance

- Prefer plan-style messages such as:
  - today's bias
  - buy/sell zones
  - invalidation
  - targets
  - next reassessment window
  - current stance: waiting / no trade / ready if trigger confirms
- Avoid repetitive messages equivalent to “checked again, still nothing”.
- A higher-frequency backend poll is acceptable only if user-facing delivery stays quiet when unchanged.

## Pitfalls

- Do not migrate production to the new runtime until live verification passes.
- Do not confuse “execution path works” with “entry logic is good”.
- **SMC analysis is new — 16 concepts, 204 tests, zero live track record as of 2026-08-08.** Treat SMC as promising but unproven. Monitor accuracy vs classic over 20+ live trades before increasing merge weight.
- **`_build_live_plan` context nesting trap.** `build_plan_from_context()` only serializes `ctx["context"]` into the plan — it silently drops top-level keys like `ctx["smc"]` or `ctx["merged"]`. When enriching the context dict with new analysis modules, nest them inside the context sub-dict: `ctx.setdefault("context", {})["smc"] = ...`, never `ctx["smc"] = ...`. Quality fields (direct ctx keys) ARE preserved, so `plan.quality.smc_confidence` can appear populated while `plan.context.smc` is empty — a misleading split. Discovered 2026-08-08.
- **Dead code trap: new SMC detectors must be wired into `smc_analyse()`.** Writing a detector function and passing its tests is not enough — it must also be called inside `smc_analyse()` and its output added to the return dict. 8 advanced concepts (breaker, rejection, OTE, Power of 3, turtle soup, silver bullet, session liquidity, volume imbalance) were defined but never called — 47% dead code until 2026-08-08. After adding any detector: (a) call it in `smc_analyse()`, (b) add to return dict, (c) update `_empty_smc_result()`, (d) verify it appears in `plan.context.smc.*` after a live build. The OTE zone returns a lambda (`in_zone`) that must be stripped before JSON serialization.
- **SMC single-timeframe blindness.** `smc_analyse()` used only M15 (80 candles = 20h). Higher-TF context was missing. Fixed by adding `h1_rows` parameter: H1 OBs/FVGs/structure computed separately, P&D swing uses H1 (15 candles = 15h) when available. Always pass `h1_rows=h1` from `_build_live_plan`.
- **SMC bias override in range regime.** Classic regime=range → bias=neutral, but SMC merge overrode to directional, producing plans with bias but no execution targets (range had empty tp_levels). Fixed with explicit guard: if `classic_regime == "range"` and merged bias ≠ neutral → force neutral, cap confidence at 0.3, action=wait.
- **Value zone too wide.** `compute_value_zone()` used raw min/max of 80 H1 candles (spread $150–$170, 30–40× ATR). Switched to 10th/90th percentile for tighter, more realistic zones.
- **Market-closed cross-cron inconsistency.** When the market is closed (weekend, holiday), multiple cron jobs running on the same stale data will produce different, contradictory analyses. The collector's SMC/classic/macro analysis runs on flat/old data and hallucinates directional biases and bogus confidence scores. Two separate LLM invocations reading this garbage reach different wrong conclusions — one says "bullish SMC, confidence 0.87" while another says "contradiction, confidence 0.3, all OBs mitigated." The user sees conflicting messages and rightfully questions the system's reliability. **Fix:** Add a freshness gate BEFORE all heavy analysis in the collector. Check tick quote_age — if >300s, produce a minimal, fixed, identical output (all biases neutral, market closed). Wire the same gate into the review script (snapshot >30min old → return "بازار بسته"). Update the oversight cron prompt to [SILENT] on market-closed output. See `references/oversight-layer.md` → "Market-Closed Gate" for the complete implementation pattern.
- **Range regime empty tp_levels.** `_build_execution_plan` returned empty lists for range regime. Now returns value zone edges as targets (0.5/0.5 split) with breakout/pullback triggers for mean-reversion entries.

## Verification

- Verify tests for lifecycle, runtime state, reporting, and orchestration.
- Verify live behavior in sequence:
  1. first run builds/stores a plan
  2. next run monitors against the stored plan
  3. unchanged state produces no user-facing output
  4. meaningful change produces a Persian plan/report message
  5. execution path reaches the direct MT5 adapter when conditions are met

## References

- See `references/reporting-cadence.md` for the recommended cadence, event triggers, and Persian report shape.
- See `references/smc-architecture.md` for SMC engine merge flow, confidence scaling, killzone sessions, and test suite.
- See `references/oversight-layer.md` for the Hermes review loop: snapshot format, wiring point, cron job pattern, and OmniRoute combo debugging for cron failures.
