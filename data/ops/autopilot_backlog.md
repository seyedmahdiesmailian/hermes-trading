# Hermes Trading — Autopilot Backlog

Rules for every autopilot run: pick ONE item (top of list with status `todo`),
finish it, verify (tests + live cycle), move it to `done` with a dated note.
If nothing left: audit a new area, add findings here, pick the highest-value one.

**Hard limits:** never execute trades, never touch DRY_RUN/positions/bridge/Windows,
never weaken risk gates. Code quality & analysis only. All changes must keep
`python3 -m unittest discover -s tests` green and pass a real `hermes_master.py` cycle.

## Active
- [ ] A/B the aggressive premium/discount entry path: backtest with those branches
      disabled vs enabled (parity funnel) — do they add or bleed PnL? Decide from data.
- [ ] Journal by session+regime: extend learning.py analyze() to break down by
      (asia/london/newyork) × (trend/range) so risk_mult can become session-aware later.
- [ ] Backtest robustness: run the parity funnel on 3+ separate 500-bar windows
      (different weeks if broker history allows, else offsets) — report variance of WR/PnL.
- [ ] Spread/slippage sensitivity: rerun backtest with spread 0.35 and 0.50 — does
      edge survive realistic costs?
- [ ] Zone-width sanity: long/short entry zones are 0.5 ATR wide from a 12-bar window —
      test 8/12/20-bar lookbacks in the parity funnel, pick best by PnL+trades.
- [ ] Alert hygiene: master.log 'execute=True' events — verify a Telegram report fires
      within 60s of every live execution (check report path in hermes_master.py).

## Done
- [x] 2026-08-29 Analysis-chain audit round 2 (context.py math, macro chain, plan funnel):
      ATR→true-range; bias threshold volatility-relative; trend_strength ATR-normalized
      (was saturating every gate: grade always A, vol always high, momentum always 1.0);
      FF calendar currency field fixed (was empty → filter passed everything);
      macro_filter date-key fixed + wired into BOTH entry paths (plan + signal) —
      news blackout was dead in production; removed 7 dead functions;
      backtest now runs the EXACT live funnel (parity by construction, no hand-copied
      gates) → 26 trades / 61% WR / +92.39 USD on 7.4 days of real M15 data. 52 tests green.
