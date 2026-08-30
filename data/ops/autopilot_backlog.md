# Hermes Trading — Autopilot Backlog

Rules for every autopilot run: pick ONE item (top of list with status `todo`),
finish it, verify (tests + live cycle), move it to `done` with a dated note.
If nothing left: audit a new area, add findings here, pick the highest-value one.

**Hard limits:** never execute trades, never touch DRY_RUN/positions/bridge/Windows,
never weaken risk gates. Code quality & analysis only. All changes must keep
`python3 -m unittest discover -s tests` green and pass a real `hermes_master.py` cycle.

## Active
- [ ] env_loader fallback for remaining scripts: _check_bridge.py, autopilot_digest.py,
      backtest_sweep.py still import dotenv bare (crash without python-dotenv); and
      ab_aggressive_entry.py + scripts/backtest_robustness.py hand-parse .env —
      switch all to the shared env_loader.load_dotenv() pattern.
- [ ] Spread/slippage sensitivity: rerun backtest with spread 0.35 and 0.50 — does
      edge survive realistic costs?
- [ ] Zone-width sanity: long/short entry zones are 0.5 ATR wide from a 12-bar window —
      test 8/12/20-bar lookbacks in the parity funnel, pick best by PnL+trades.
- [ ] Alert hygiene: master.log 'execute=True' events — verify a Telegram report fires
      within 60s of every live execution (check report path in hermes_master.py).
- [ ] Reusable A/B template: scripts/ab_aggressive_entry.py pattern (one cached
      dataset + run_backtest(data=...) + exclude_styles prefixes in backtest_ohlc)
      — reuse for future branch A/Bs: SMC range-kill rule on/off, macro blackout
      on/off, BE-at-R 0.4 vs 0.5.
- [ ] Ticket→plan linkage: execution_log.csv has no ticket column and orders carry no
      Hermes comment, so journal trades can only be attributed to plans by time
      proximity (48h lookback in learning.analyze). Add 'ticket' to the
      append_execution_log rows in hermes_runtime.py + signal_listener.py (result
      already contains it) so future regime joins are exact, not heuristic.

## Done
- [x] 2026-08-30 Backtest robustness: parity funnel on 13 NON-OVERLAPPING 500-bar
      windows (separate weeks, May 21→Aug 28, broker history allowed, one cached
      dataset; H1/H4 context time-padded before each window). Variance: PnL mean
      +132.66 sd 118.83 (min −57.84 / max +434.81), WR mean 50.6% sd 12.7
      (26.9→79.2), trades ~26/week sd 3. 12/13 weeks profitable, +1724.61 total
      over 341 trades — edge is broad, not a few lucky weeks; one bad week
      (late May) ≈ 0.5R of a normal week. Tools: scripts/backtest_robustness.py
      (resumable, window-by-window state files), results in
      data/backtest/robustness_results.json. 71 tests green, live cycle OK.
- [x] 2026-08-30 CRITICAL FIX found by the run gate: python-dotenv missing on this
      box → hermes_master's `except ImportError: load_dotenv = lambda: None`
      silently skipped .env → no bridge token → 401 → 'insufficient_market_data'
      on EVERY direct cycle (pre-existing since at least 08-28; one prior
      autopilot even mislabeled it 'weekend, expected'). Cron masked it by
      exporting .env in the wrapper. Fix: engines/env_loader.py fallback
      (dotenv-compatible: no-override, quotes, comments) wired into the 4 core
      entrypoints + tests/test_env_loader.py; gate now passes.
- [x] 2026-08-30 Journal by session+regime: analyze() now emits by_session and
      by_session_regime (asia/london/newyork × trend/range/unknown); session bounds
      parity-tested against hermes_runtime._detect_session; regime joined via
      time-proximity to execution_log (dry-run/failed excluded, 48h lookback) →
      plan_history quality.regime. Finding: all 5 journaled trades pre-date any
      logged successful execution → regime='unknown' (honest, not guessed); exact
      join impossible until execution_log gains a ticket column → new todo added.
      64 tests green, live cycle OK.
- [x] 2026-08-30 A/B aggressive premium/discount entries (parity funnel, 3000 M15 bars
      ~31 days, spread 0.20, one cached dataset for all runs): KEEP — they ADD ~80% of PnL.
      Baseline (live) 156 trades / 57.0% WR / +807.76; PD-aggressive disabled 60 / 56.7% /
      +161.22; all aggressive disabled 40 / 65.0% / +123.24. Per-style: aggressive_premium
      n=81 +448.49, aggressive_discount n=56 +319.56, aggressive_value n=6 +22.80,
      pullback n=13 +16.91. Geometry sane (max win 68.3 / max loss −36.5). Decision:
      live behaviour unchanged. Tools added: exclude_styles prefix filter + style tag in
      backtest_ohlc/run_backtest (53 tests green), scripts/ab_aggressive_entry.py,
      results in data/backtest/ab_aggressive_results.json.
- [x] 2026-08-29 Analysis-chain audit round 2 (context.py math, macro chain, plan funnel):
      ATR→true-range; bias threshold volatility-relative; trend_strength ATR-normalized
      (was saturating every gate: grade always A, vol always high, momentum always 1.0);
      FF calendar currency field fixed (was empty → filter passed everything);
      macro_filter date-key fixed + wired into BOTH entry paths (plan + signal) —
      news blackout was dead in production; removed 7 dead functions;
      backtest now runs the EXACT live funnel (parity by construction, no hand-copied
      gates) → 26 trades / 61% WR / +92.39 USD on 7.4 days of real M15 data. 52 tests green.
