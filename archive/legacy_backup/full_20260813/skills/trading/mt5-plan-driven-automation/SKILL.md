---
name: mt5-plan-driven-automation
description: "Use when MT5 trading should be plan-driven and quiet."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [mt5, trading, automation, xauusd, cron, direct-api, reporting, runtime, persian]
---

# MT5 Plan-Driven Automation

## Use when
- Building or refactoring MT5 automation toward a **plan-first** workflow.
- Replacing noisy scan-driven polling with **stateful plan / monitor / reassess** runtime behavior.
- The user wants **direct MT5 Python API** control, concise operator-facing reports, and quiet operation unless something meaningful changed.
- The system should feel like a disciplined trader with a thesis, not a perpetual scanner.

## Core principles
1. **Plan first, execution second.** Build a market plan, persist it, then monitor against that plan.
2. **Decision belongs in Hermes, analysis and execution in code.** For the fully autonomous brain-apprentice architecture where Hermes is the primary decision-maker (not just overseer), see `autonomous-trading-agent-design` and its `references/hybrid-architecture-v4.md`. This skill covers the plan-driven foundation used by that architecture.
3. **Direct API only when requested.** If direct MT5 Python API is the chosen operating mode, do not regress to bridge/EA/file fallback paths.
4. **Quiet by default.** User-facing cron output should be emitted only on meaningful state changes.
5. **Production cutover only after verification.** Keep legacy runtime in place until the new runtime passes tests and live verification.

## Recommended runtime shape
Use a three-step state machine:
- `plan`: build or rebuild the active plan
- `monitor`: compare live price against the active plan
- `reassess`: rebuild the plan at scheduled review windows

Persist at minimum:
- current plan
- runtime state
- execution log
- reassessment log
- plan history archive

## Reporting pattern
Operator-facing reports should be:
- **Persian-first when the user prefers Persian**
- short, scan-friendly, and meaningful
- event-style rather than heartbeat spam

Good operator messages:
- morning/session plan summary
- reassessment summary
- price entered key zone
- trigger confirmed / waiting for trigger
- order sent / failed
- setup invalidated

Bad operator messages:
- unchanged monitor output every few minutes
- repeated "still nothing" pings
- long code-centric dumps
- over-explaining implementation when the user asked for operational status

## Cadence guidance
Separate backend polling from user-facing reporting.

- Backend may poll more often if needed for execution safety.
- User-facing cron/reporting should be slower and quieter.
- Prefer **silent-on-no-change** behavior.
- Prefer session-based reports (morning / London reassessment / New York reassessment) plus important alerts.

A good default for this style is:
- scheduled monitoring at a moderate interval (for example 10–15 minutes)
- message delivery only on meaningful change

## Progress-reporting style for build/migration sessions
When the user wants proof that work is actually happening, give **short, verifiable checkpoints** instead of essays.

Preferred checkpoint template:
- Done
- Files
- Tests
- Live verify
- Blockers
- Next

Rules:
- Report only things that actually happened.
- Include real file paths, real test results, and real live verification outputs when available.
- Avoid repeated promises without new artifacts.

## Migration workflow
1. Build the new runtime in separate files.
2. Add tests first for each new lifecycle/reporting behavior.
3. Verify the new runtime against real MT5 data.
4. Add the new wrapper/script path.
5. Cut cron over to the new path.
6. Keep a legacy backup wrapper for rollback.
7. Verify post-cutover behavior before declaring success.

## Analysis pipeline (XAUUSD)

The production runtime merges two analysis layers inside `mt5_xau_runtime.py`:

1. **Classic context** (`mt5_xau_context.py`) — bias, value zones, ATR, regime.
2. **SMC engine** (`mt5_xau_smc.py`) — Smart Money Concepts as the primary brain (user-approved direction): order blocks, FVG, liquidity sweeps, market structure (BOS/CHoCH), premium/discount, killzones, POI grading, plus advanced concepts (breaker/rejection blocks, OTE, Power of Three, turtle soup, silver bullet, session liquidity, volume imbalance).
3. **Merge** (`merge_smc_with_classic`) — weighted consensus, SMC-favored (~0.6 weight). When classic is neutral, SMC overrides; on conflict, classic wins (conservative).

Extend analysis by adding detectors to `mt5_xau_smc.py` TDD-first (tests live in `tests/test_mt5_xau_smc.py`), then wiring them into `smc_analyse` / the merge — do not bolt new signal logic directly onto the runtime.

## Pitfalls
- **OpenBLAS threading conflicts with MT5 data processing.** Python scripts using numpy/pandas with MT5 can hit `OpenBLAS error: Memory allocation still failed after 10 retries, giving up` when multiple threads compete for memory allocation. This typically occurs during large historical data fetches (100k+ bars) or when MT5 terminal + multiple Python processes run simultaneously. **Fix: Set thread limits before importing numpy:** `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python script.py`. For cron jobs, add these environment variables to the job or script wrapper. The error is threading-related, not actual memory shortage — 8GB RAM with 3.8GB free is sufficient.
- **Self-defeating fixtures in detector tests.** The SMC detectors use adaptive thresholds computed FROM the input data (e.g. `body >= avg_body * 1.5`, `volume >= avg_volume * 2.5`). A fixture candle with an outsized body/volume skews the average and the detector never fires — tests fail with `len([]) >= 1` or a ratio just under threshold. Before writing assertions: hand-compute the threshold for the fixture (or run the detector on it in a one-liner and print the result), keep non-trigger rows uniform and small, and check the `_candles` helper tuple order `(open, high, low, close)` before authoring data. This bit repeatedly in the SMC test suite.
- **Do not leave reassessment only half-wired.** If routing supports `reassess`, runtime must actually execute it end-to-end and log it.
- **Do not confuse frequent polling with good operator UX.** Polling cadence and reporting cadence are different concerns.
- **Do not spam unchanged status.** For no-agent cron jobs, empty stdout is a useful silence mechanism.
- **Do not disable the old runtime before the new one is verified.** Cut over only after tests and live checks succeed.
- **Do not bury user style corrections in memory only.** If the user wants concise, low-noise MT5 status, encode that in the workflow skill.
- **Do not let implementation updates replace operator analysis.** The user may want the agent to own the scenario framing while code handles persistence and execution.

## Verification checklist
Before declaring the new runtime complete:
- [ ] lifecycle tests pass
- [ ] execution-path tests pass
- [ ] reassessment-path tests pass
- [ ] full suite passes
- [ ] live MT5 plan creation verified
- [ ] live monitor behavior verified
- [ ] post-cutover wrapper verified
- [ ] cron points to the new script
- [ ] unchanged monitor cycles stay silent

## Example concise Persian report shapes
### Plan
- `پلن طلا | XAUUSD | bullish`
- `خرید 4106-4111 | فروش 4248-4253`
- `بازبینی 2026-08-07T13:00:00+00:00`

### Monitor
- `پایش طلا | XAUUSD | bullish`
- `اقدام no_trade | ناحیه premium | قیمت 4305.93`

### Checkpoint to the user during development
- Done: runtime reassessment wired
- Files: `...mt5_xau_runtime.py`, `...test_mt5_xau_reassessment.py`
- Tests: `43 passed`
- Live verify: silent on unchanged state
- Blockers: none
- Next: improve trigger quality

## Notes
This skill overlaps with more general MT5 direct-control skills. If both exist, keep this one focused on **plan-driven runtime architecture, reporting cadence, and migration discipline**, while the direct-control skill stays focused on order/account/symbol mechanics.
