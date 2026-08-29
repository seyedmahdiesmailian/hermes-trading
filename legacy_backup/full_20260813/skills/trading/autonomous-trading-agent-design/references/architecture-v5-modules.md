# XAUUSD Architecture v5.0 — Module Reference

Built 2026-08-08. Documents the standalone modules that implement v4→v5 professional features.

## Module Map

| Module | Purpose | Key Export |
|--------|---------|------------|
| `mt5_xau_macro.py` | DXY proxy, SPX risk, silver, volume, H4/D1/W1 alignment | `build_macro_snapshot(mt5)` → dict |
| `mt5_xau_calendar.py` | ForexFactory economic calendar, news risk detection | `get_calendar(days_ahead)` → dict, `is_news_risk_active(hours_before, hours_after)` → dict |
| `mt5_xau_trade_mgr.py` | BE, trailing stop, partial TP, time exit, news lock | `evaluate_trade_management(pos, ...)` → action dict, `get_sl_tp_blueprint(entry, direction, atr, regime)` → dict |
| `mt5_xau_session.py` | Session detection, kill zones, risk adjustment per session | `get_session(now)` → dict, `should_trade(now)` → (bool, reason) |
| `mt5_xau_divergence.py` | Multi-TF RSI divergence detection | `multi_tf_divergence(m5, m15, h1)` → dict, `detect_divergence(rows)` → dict |
| `mt5_xau_defcon.py` | Closed-trade feedback loop, DEFCON levels | `compute_trading_insights(perf, account)` → dict, `filter_management_by_insights(mgmt, insights)` → dict, `filter_entry_by_insights(allowed, reason, insights)` → dict |
| `mt5_xau_presession.py` | Pre-London analysis, daily scenarios | `run_presession_analysis()` → saves plan JSON |
| `mt5_xau_weekly_review.py` | Sunday journal review, auto-patch suggestions | `run_weekly_review()` → saves learning report |
| `mt5_xau_decision_collector.py` | Central collector — ties all modules together | `collect()` → (raw, analysis, summary) |

## DEFCON Standalone Module (`mt5_xau_defcon.py`)

Implements the full closed-trade feedback loop from references/closed-trade-feedback-loop.md as a standalone module:

```
snapshot_closed_deals(days_back) → classify_exits(deals) → analyze_exits(classified)
                              ↓
              compute_trading_insights(perf, account)
                              ↓
       filter_management_by_insights(mgmt, insights)  |  filter_entry_by_insights(allowed, reason, insights)
```

### DEFCON Levels

| Level | Trigger | Effect |
|-------|---------|--------|
| GREEN | Default | All actions allowed, full risk |
| YELLOW | loss_streak ≥ 2 OR (sl_ratio ≥ 0.5 AND total ≥ 3) | Half risk, runners disabled, scale-ins disabled |
| RED | total ≥ 5 AND sl_dominant AND daily_pnl < 0 | No new entries, manage existing only |

### Exit Classification
Parses `comment` field from MT5 deal history:
- `[sl ...]` → `sl`
- `[tp ...]` → `tp`  
- `Hermes manage` / `partial` / `trail` → `managed`
- else → `unknown`

## Trade Management Priority Order

Critical architectural decision: action priority matters.

```
1. news_lock  (safety — tighten SL before high-impact event)
2. time_exit  (safety — exit positions open too long)
3. partial_tp (profit — take partial at target R)
4. trail      (profit — lock in gains with trailing stop)
5. move_be    (risk — move SL to breakeven when R ≥ 0.5)
6. hold       (default)
```

BE is checked LAST because it's the lowest-priority active action. If both BE (0.5R) and partial TP (1.6R) conditions are met, partial TP wins because it's checked first. This prevents BE from shadowing higher-value actions.

## Session Integration

Session analysis (`mt5_xau_session.py`) feeds into:
1. **Collector**: session_detail, session_risk, killzone list in analysis dict
2. **Decision loop**: Hermes sees session quality and adjusts aggression
3. **Risk**: Asian session without killzone → risk × 0.5

Kill zones (UTC): Asian Range (0-2), London Open (7-9), London Close (11-13), NY Open (13-15), London/NY Overlap (13-16), NY Close (18-20), Silver Bullet AM (7-9), Silver Bullet PM (12-14).

## M5 Timeframe

Added to collector at 100 bars. Provides:
- M5 Classic bias + ATR
- M5 SMC bias + confidence + last 5 FVGs + last 3 OBs
- Alignment check: M5 classic + M5 SMC same direction = stronger signal
- M5+ M15+H1 divergence confluence = strongest reversal signal

## Cron Jobs

| Job | Schedule | Script | Purpose |
|-----|----------|--------|---------|
| 549e6796fd3e | every 15m | mt5_xau_decision_collector.py | Main decision loop |
| 6acc2e00a4d8 | 30 6 * * 1-5 | mt5_xau_presession.py | Pre-London analysis |
| d582a7fe0a68 | 30 18 * * 0 | mt5_xau_weekly_review.py | Weekly learning review |
| dcbb59fbf158 | every 120m | — | Heartbeat monitoring |
