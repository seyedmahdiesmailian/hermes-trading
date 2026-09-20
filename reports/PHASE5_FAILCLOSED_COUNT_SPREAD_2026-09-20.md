# Phase 5 — fail-closed entry count + spread (2026-09-20)

Two remaining fail-open holes after `87409f8`. Neither is a sizing/style
change. Both are the b45/b30 class: an unreadable input used to look like
"safe to enter".

## 1. Open-position count (b45 wearing a 401 hat)

`positions_list()` / `position_count()` return `[]` / `0` on `{ok:false}`
(401, MT5 error, dict `data`). That is correct for the **daemon** (empty
live-map must not mark every tracked ticket CLOSED → duplicate reopen).

It is wrong for the **entry** gate: 0 reads as "slot free" and
`MAX_OPEN_POSITIONS=1` goes blind — the 14:15/14:30 UTC double-sell
(-$94.7) class.

New reader `engines.bridge_payload.entry_open_count(resp, slot_full=1)`:

| shape | `position_count` | `entry_open_count` |
|---|---|---|
| `{ok:true, data:[pos]}` | 1 | 1 |
| `{ok:true, data:[]}` | 0 | 0 |
| `{ok:false, data:{...}}` 401 | 0 | slot_full |
| exception / non-dict / data not list | 0 | slot_full |

Wired in:

* `hermes_runtime._performance_and_policy` (plan path → `evaluate_proposal` Check 5)
* `engines.signal_listener.check_signals` (scorer `already_in_position`; live
  execution still hard-blocks via `_performance_and_policy` → Check 5)

`positions_list` is unchanged. Do not merge the two readers.

## 2. Plan-path spread gate (b30 class)

`cycle()` used `except (TypeError, ValueError): pass` around ask-bid.
An unreadable tick left the proposal unguarded. The signal path already
fail-closed (`tick_unavailable_fail_closed`).

`_entry_spread_veto(tick)` now blocks on missing / non-numeric / inverted /
zero / wide spread. `monitor['spread_blocked']` still feeds the b171 brief.

Signal path also refuses `_spr <= 0` (parity).

## Explicitly not done

* `policy.risk_multiplier` (double-charge vs `TIGHT_REGIMES`)
* clock-fallback `plan.session`
* Friday 21:00 / Sunday 22:00 (b93 pins 22:00 / 23:00)
* post-close cooldown
* `MIN_STOP_DISTANCE` 8 → 9
* spread check inside `evaluate_proposal` when `bridge is None`
* hard-skip `already_in_position` in the scorer (still −0.5; the executor
  gate is the hard block)

Bridge / auth / `windows_bridge/` untouched. `master` untouched.
