# Closed-Trade Feedback Loop Implementation

Chain: `_load_closed_trade_snapshots` → `_classify_closed_trade` → `_build_exit_analysis` → `_build_trading_insights` → `_filter_management_by_insights` + `_filter_entry_by_insights`

Helper to avoid duplication across management + entry paths:
`_compute_trading_insights(account, now)` — wraps the full chain and returns `{performance_state, account_policy, insights, exit_analysis}`

## 1. Snapshot (`_load_closed_trade_snapshots`, mt5_xau_runtime.py)

```python
def _load_closed_trade_snapshots(days: int = 7):
    start = datetime.now(timezone.utc) - timedelta(days=days)
    end = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(start, end) or []
    snapshots = []
    for deal in deals:
        if str(getattr(deal, "symbol", "")) != "XAUUSD":
            continue
        if int(getattr(deal, "entry", -1)) != mt5.DEAL_ENTRY_OUT:
            continue
        comment = str(getattr(deal, "comment", "") or "")
        magic = int(getattr(deal, "magic", 0) or 0)
        if magic != 20260806 and not comment.startswith("Hermes"):
            continue
        # ... build snapshot dict with ticket, symbol, profit, volume, price, time, comment, magic, order, position_id
    return sorted(snapshots, key=lambda item: item["ticket"])
```

Filters: XAUUSD only, DEAL_ENTRY_OUT only, Hermes-engine or managed trades only.

## 2. Classify (`_classify_closed_trade`, mt5_xau_runtime.py)

```python
def _classify_closed_trade(deal) -> dict:
    comment = str(getattr(deal, "comment", "") or "")
    if comment.startswith("[sl "):
        return {"exit_type": "sl", "pnl": profit, "ticket": ticket, "time": time, "managed": False}
    if comment.startswith("[tp "):
        return {"exit_type": "tp", "pnl": profit, "ticket": ticket, "time": time, "managed": False}
    if "Hermes manage" in comment:
        return {"exit_type": "partial", "pnl": profit, "ticket": ticket, "time": time, "managed": True}
    return {"exit_type": "unknown", "pnl": profit, "ticket": ticket, "time": time, "managed": False}
```

## 3. Analyze (`_build_exit_analysis`, mt5_xau_runtime.py)

Returns dict:
- `total_closed`: total count
- `sl.count`, `sl.total_pnl`: SL exit stats
- `tp.count`, `tp.total_pnl`: TP exit stats
- `partial.count`, `partial.total_pnl`: managed exit stats
- `sl_dominant`: True if sl_ratio >= 0.5
- `sl_ratio`: sl_count / total
- `avg_sl_loss`: average SL loss
- `managed_total_pnl`: sum of managed exits' PnL
- `managed_win_ratio`: fraction of managed exits with positive PnL

## 4. Insights / DEFCON (`_build_trading_insights`, mt5_xau_runtime.py)

Input: exit_analysis + performance_state + account_policy

| DEFCON | Condition | Effect |
|--------|-----------|--------|
| GREEN | default | all actions allowed |
| YELLOW | loss_streak ≥ 2 OR (sl_ratio ≥ 0.5 AND total ≥ 3) | runners disabled, scale-ins disabled, partials allowed, risk_override = base × 0.75 |
| RED | total ≥ 5 AND sl_dominant AND daily_pnl < 0 | no new entries, runners disabled, scale-ins disabled, partials allowed |
| Additional | managed_pnl < 0 AND managed_win ≤ 0.3 | runners and scale-ins disabled (regardless of DEFCON) |

Returns: `{defcon, partial_allowed, runner_allowed, scale_in_allowed, risk_override, trade_allowed}`

## 5. Management Filter (`_filter_management_by_insights`, mt5_xau_runtime.py)

```python
def _filter_management_by_insights(management: dict, insights: dict) -> dict:
    action = management.get("action", "hold")
    if action == "hold":
        return management
    # Safety valves always allowed
    if action in {"close_trade_early", "partial_take_profit", "move_stop_to_breakeven"}:
        return management
    # Runner disabled → force close
    if not insights.get("runner_allowed", True) and action in {"trail_stop", "close_runner"}:
        return {"action": "close_runner", "close_fraction": 1.0,
                "reason": f"insights:defcon_{insights.get('defcon')}:runner_blocked"}
    # Scale-in disabled → hold
    if not insights.get("scale_in_allowed", True) and action.startswith("scale_in"):
        return {"action": "hold",
                "reason": f"insights:defcon_{insights.get('defcon')}:scale_in_blocked"}
    return management
```

## 6. Entry Filter (`_filter_entry_by_insights`, mt5_xau_runtime.py)

```python
def _filter_entry_by_insights(sizing_allowed: bool, sizing_reason: str | None, insights: dict | None) -> dict:
    """Returns {"allowed": bool, "risk_pct_override": float|None, "reason": str|None}"""
    if insights is None:
        return {"allowed": sizing_allowed, "risk_pct_override": None, "reason": sizing_reason}
    if not sizing_allowed:
        return {"allowed": False, "risk_pct_override": None, "reason": sizing_reason}
    if not insights.get("trade_allowed", True):
        return {"allowed": False, "risk_pct_override": None,
                "reason": f"defcon_{insights.get('defcon', 'red')}:entry_blocked"}
    risk_override = insights.get("risk_override")
    return {"allowed": True, "risk_pct_override": risk_override, "reason": None}
```

Rules:
- `trade_allowed=False` (DEFCON=RED) → blocks entry entirely
- `risk_override` set (DEFCON=YELLOW) → returns reduced risk_pct, but caller must apply it
- Grade C / position_limit blocks still respected (sizing_allowed=False passes through)

## 7. Runtime Integration (in `main()`, mt5_xau_runtime.py)

### Management path:
```python
if positions:
    account = mt5.account_info()
    trading = _compute_trading_insights(account, now)  # ← helper, one call
    insights = trading["insights"]

    for position in positions:
        management = _select_management_decision(plan, position, tick, runtime_state=runtime, now=now)
        if management:
            management = _filter_management_by_insights(management, insights)
            execution_result = _execute_management_action(position, management)
```

### Entry path:
```python
if monitor.get("action") == "market_order":
    trading = _compute_trading_insights(account, now)  # ← same helper
    insights = trading["insights"]
    # ...
    sizing = _build_execution_sizing(monitor["blueprint"], info, account_policy, setup_grade)

    entry_guard = _filter_entry_by_insights(
        sizing.get("meaningful"), sizing.get("reason"), insights
    )
    if not entry_guard["allowed"]:
        monitor = {"action": "no_trade", "reason": entry_guard["reason"], ...}
        # emit and return — no trade
```

### Payload:
Include `insights` (defcon, runner_allowed, scale_in_allowed, trade_allowed) in management output payload for observability.

## Test Files

- `tests/test_mt5_xau_setup_memory.py`: 5 tests for `_classify_closed_trade` (sl, tp, partial, managed, ticket order)
- `tests/test_mt5_xau_exit_analysis.py`: 4 tests for `_build_exit_analysis` (sums, empty, sl_dominant, managed value)
- `tests/test_mt5_xau_trading_insights.py`: 5 tests for `_build_trading_insights` (green, red, yellow, empty, loss_streak+good_rr)
- `tests/test_mt5_xau_insights_filter.py`: 4 tests for `_filter_management_by_insights` (green, yellow, red, hold never blocked)
- `tests/test_mt5_xau_entry_guard.py`: 5 tests for `_filter_entry_by_insights` (green, yellow, red, grade_c_block, none_insights)
- `tests/test_mt5_xau_performance_feedback.py`: updated with storage isolation (monkeypatch load/save)

## Live Verification Pattern

When market is open and demo account has positions, verify:
1. Run runtime with positions open
2. Check that insights appear in management output payload
3. Verify that trail_stop → close_runner when DEFCON=YELLOW
4. Verify that scale_in → hold when DEFCON=YELLOW

When market is closed (no positions), run synthetic test:
```python
# Simulate management decisions under current insights
# Verify filter overrides as expected
```

## Pitfalls

- **Storage coupling**: tests that use `_update_performance_state` must monkeypatch `load_performance_state` and `save_performance_state` to avoid reading/writing the real `performance_state.json` file
- **New-day detection**: `compute_performance_state` returns a fresh state when `state.get("day") != today`, which means it won't process closed trades. Test mock states must include `"day": today_date` and a `last_closed_ticket` lower than the fake deal tickets
- **Empty history**: insights with `total_closed == 0` must not penalize — return DEFCON=GREEN with all actions allowed
- **risk_override not applied to sizing**: `_filter_entry_by_insights` returns `risk_pct_override` but the current entry path in `main()` does NOT pass it into `_build_execution_sizing` or `recommend_risk_budget`. The entry guard currently only blocks entries (RED → no_trade) or allows them with the policy-determined risk. The override value is computed but unused. Fix: modify `_build_execution_sizing` to accept an optional `risk_pct_override` parameter, or recompute sizing after filtering with the override value.
