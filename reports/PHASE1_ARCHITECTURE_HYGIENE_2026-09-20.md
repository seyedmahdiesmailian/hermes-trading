# Phase 1 — architecture hygiene (post-rebase)

Date: 2026-09-20
Branch: `arena/01a0bb28-hermes-trading` (never `master`)
Parent: geometry commit on top of `origin/master` `2fedb95`

## What landed

1. **`daily_pnl` is NET.** `engines/risk.compute_performance_state` now sums
   `profit + commission + swap`. Kill-switch / daily-loss / DEFCON gates that
   read this number were a round of fees too optimistic. Opening deals
   (entry=0 / IN) still contribute their fees to the day total but do **not**
   increment `loss_streak` (b89 contract: opens are profit 0.0 and must not
   touch the streak arm). Tightening only.

2. **Loads do not mkdir.** `load_current_plan` / `load_runtime_state` /
   `load_performance_state` resolve paths with `create=False`. A missing tree
   is a missing plan, not a reason to create production directories as a
   side-effect of a read. Writes still go through `ensure_xau_plan_dirs`.

3. **Dashboard sees the 9 live units.** `_services()` queries the 8 systemd
   services in `ops/systemd/` plus `hermes-trading.timer`. The old list of 4
   made «همه‌چیز روال است» while forwarder / webui / omniroute were down.
   RESTARTABLE is unchanged (operator restart still the three daemons).

## Deliberately not changed

- Cycle copy stays «هر ۱۵ دقیقه»: `ops/systemd/hermes-trading.timer` is
  `OnUnitActiveSec=15min`. Lying and saying 5 minutes would be worse than
  the stale-looking copy.
- `windows_bridge/`, `_deploy_bridge.py`, `mt5_http_server_v2.py` — not
  touched (standing order).
- `master` — not touched.
- DEFCON window is still last-10 **deals** (b89 option (b)). Ledger SHA
  stamps in `data/backtest/b88_defcon_books.json` and
  `b89_window_contract.json` were updated because `risk.py` bytes changed;
  the replay numbers are invariant (lab deals have no commission/swap).

## Pins

`tests/test_architecture_hygiene.py` — net PnL, open-deal streak isolation,
load-without-mkdir, 9-unit dashboard list.
