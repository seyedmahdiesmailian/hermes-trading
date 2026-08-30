# Hermes Trading — Autopilot Backlog

Rules for every autopilot run: pick ONE item (top of list with status `todo`),
finish it, verify (tests + live cycle), move it to `done` with a dated note.
If nothing left: audit a new area, add findings here, pick the highest-value one.

**Hard limits:** never execute trades, never touch DRY_RUN/positions/bridge/Windows,
never weaken risk gates. Code quality & analysis only. All changes must keep
`python3 -m unittest discover -s tests` green and pass a real `hermes_master.py` cycle.

## Active
- [x] Spread gate for live entries (done 2026-08-30: MAX_ENTRY_SPREAD=0.60 in hermes_runtime, env HERMES_MAX_SPREAD, entry-path only): the parity funnel never looks at real-time
      spread (cost is linear in trades, verified 2026-08-30), so news/rollover
      spikes (XAUUSD can blow past 2.0) are unguarded in live. Evaluate a
      max-spread pre-entry gate in hermes_runtime (read-only tick check, e.g.
      skip if ask-bid > 0.60) — propose threshold from tick history, do NOT
      weaken existing gates.
- [x] Zone-width sanity (done 2026-08-30: A/B 8/12/20 bars on 13 M5 windows — 8: 12/13 prof +970/225t, 12: 13/13 +949/206t, 20: 13/13 +788/179t → keep 12, best balance): long/short entry zones are 0.5 ATR wide from a 12-bar window —
      test 8/12/20-bar lookbacks in the parity funnel, pick best by PnL+trades.
- [ ] Alert hygiene: master.log 'execute=True' events — verify a Telegram report fires
      within 60s of every live execution (check report path in hermes_master.py).
- [ ] Reusable A/B template: scripts/ab_aggressive_entry.py pattern (one cached
      dataset + run_backtest(data=...) + exclude_styles prefixes in backtest_ohlc)
      — reuse for future branch A/Bs: SMC range-kill rule on/off, macro blackout
      on/off, BE-at-R 0.4 vs 0.5.
- [x] Ticket→plan linkage (done 2026-08-30: ticket column in execution_log + exact join in learning.analyze, proximity kept as fallback): execution_log.csv has no ticket column and orders carry no
      Hermes comment, so journal trades can only be attributed to plans by time
      proximity (48h lookback in learning.analyze). Add 'ticket' to the
      append_execution_log rows in hermes_runtime.py + signal_listener.py (result
      already contains it) so future regime joins are exact, not heuristic.

## Done
- [x] 2026-08-30 Spread/slippage sensitivity: edge is cost-INSENSITIVE — spread is a
      linear per-trade tax (entry/exit geometry unchanged), measured on the 13 cached
      robustness windows via run_backtest(spread_override=...): gross 0.00 → +1112.95,
      0.20 (live) → +1065.64, 0.35 → +1030.19, 0.50 → +994.70; identical 196 trades,
      63.2% WR, 12/13 profitable windows at EVERY level; break-even spread ≈ 2.86
      (16x the 0.18 live demo tick spread). Live assumption (0.20) is conservative.
      Tool: scripts/spread_sensitivity.py; results data/backtest/spread_sensitivity_results.json.
      Also removed dead _exit_price() in engines/backtest.py and locked the symmetric
      one-spread cost model with test_spread_symmetric_buy_and_sell. 73 tests green, live cycle OK.
- [x] 2026-08-30 env_loader fallback everywhere: 5 scripts (_check_bridge,
      autopilot_digest, backtest_sweep, ab_aggressive_entry, verify_chain) imported
      dotenv bare → crashed on this box (python-dotenv absent); backtest_robustness
      hand-parsed only HERMES_BRIDGE_TOKEN. ALL now use the shared
      try-dotenv-except-env_loader pattern. Sweep also caught 2 LIVE DAEMONS
      (position_daemon.py, signal_daemon.py) hand-parsing .env with a weaker parser
      (no quote stripping → quoted tokens passed to bridge verbatim); switched too.
      Locked in by tests/test_env_loader.py::test_every_dotenv_user_has_fallback —
      repo-wide scan that fails if any non-test .py touches .env without the
      fallback. 72 tests green, live cycle OK (reassess, execute=False).
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
