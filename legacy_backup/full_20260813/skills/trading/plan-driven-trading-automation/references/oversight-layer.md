# Hermes Oversight Layer for XAUUSD Automation

## Purpose

After each plan build, the runtime saves a review snapshot containing the full SMC and merged analysis. A separate cron job periodically reads the latest snapshot and sends it to Hermes for quality review. Hermes then compares the analysis against reality, flags issues, and suggests improvements.

## Files

| File | Role |
|------|------|
| `mt5_xau_review.py` | Save/load/format review snapshots |
| `mt5_xau_runtime.py` (wired at `_build_live_plan`) | Calls `save_review_snapshot()` after plan save |
| Cron job `Hermes XAUUSD Oversight` | Reads snapshot every 2h, sends Persian review to user |

## Snapshot Format

Saved to `trading/xau_plan/review_snapshots/latest_snapshot.json`:

```json
{
  "plan_id": "xau-abc123",
  "timestamp": "2026-08-08T09:00:00Z",
  "session": "london",
  "bias": "bullish",
  "classic": { "bias": "bullish", "regime": "trending", "trend_strength": 76.75 },
  "smc": { "bias": "bullish", "signal": "buy", "confidence": 0.72, "poi": "OB+Premium", ... },
  "merged": { "bias": "bullish", "confidence": 0.68, "agreement": true },
  "zones": { "value": [4126, 4290], "long_entry": [4123, 4126], ... }
}
```

## Wiring Point

In `mt5_xau_runtime.py`, snapshot is saved in `main()` at line ~758, inside the plan step — AFTER `_save_plan_and_state(plan, runtime, step)`:

```python
try:
    from mt5_xau_review import save_review_snapshot
    smc_data = plan.get("context", {}).get("smc", {})
    merged_data = plan.get("context", {}).get("merged", {})
    save_review_snapshot(plan, smc_data, merged_data, now)
except Exception:
    pass  # never break the pipeline for review
```

**Critical**: `plan.context.smc` is populated by `_build_live_plan()` via `ctx.setdefault("context", {})["smc"] = smc_result`. The top-level `ctx["smc"] = ...` pattern is silently dropped by `build_plan_from_context()` — see skill Pitfalls section for the context nesting trap.

## Cron Job Pattern

- Schedule: `every 2h`
- Toolsets: `["terminal", "file"]` (minimal — just needs to run Python and read files)
- Model: inherits default (`hermes-win` via OmniRoute combo)
- Prompt: reads snapshot via `python mt5_xau_review.py`, analyzes SMC vs classic agreement, OB validity, FVG logic, confidence threshold, POI/killzone correctness, and responds in Persian

## Review Output Shape

```
⚠️ پیشنهاد بهبود
• SMC بایاس صعودی (conf 0.72) با کلاسیک همراستاست
• Order Block در premium معتبر — volume بالاست
• یک نگرانی: killzone London هنوز شروع نشده — POI زودهنگامه
• پیشنهاد: تا ورود به killzone صبر کن
```

## Cron Debugging: OmniRoute Combo Failures

If the review cron fails with `HTTP 410` or provider errors, check the OmniRoute combo definition:

```bash
curl -s http://localhost:20128/api/v1/combos | python -m json.tool
```

This endpoint works without auth and shows the resolved combo models. If a provider has a dead model (e.g., nvidia's deepseek-v4-pro reached EOL 2026-08-07), the combo may need updating or the cron job may need to be recreated after the combo fix.

## Limitations

- The review cron only runs every 2h — it may miss rapid reassessments during active market hours. Consider increasing to `every 1h` during London/NY overlap.
- If the runtime hasn't produced a new plan (market closed), the snapshot will be stale. The review cron should detect this and report "بازار بسته - snapshot جدیدی موجود نیست".
- SMC data may be `None` for plans built before the oversight wiring was added (e.g., plan `xau-d64c1e58`).

## Market-Closed Gate (Critical — added 2026-08-09)

**Problem:** Two cron jobs (main decision loop + oversight reviewer) running on stale weekend data produced radically different analyses. Main cron said "market closed, wait" while oversight cron panicked about "confidence 0.3, SMC/classic contradiction, all OBs mitigated" — all on data that was 35+ hours old. The user saw contradictory messages and correctly identified the inconsistency.

**Root cause:** The collector ran full SMC + classic + macro analysis on every tick regardless of market status. On closed-market data (quote age > 5min), technical indicators produce garbage — directional biases appear from flat data, classic ranges conflict with SMC trends, confidence scores are meaningless. Two separate LLM invocations reading the same garbage reached different wrong conclusions.

**Fix (implemented in `mt5_xau_decision_collector.py`):**

1. **Gate function `_is_market_closed(raw)`:** Checks tick timestamp — if quote_age > 300s, market is closed. Runs BEFORE any heavy analysis.

2. **Minimal output `_closed_market_analysis(raw)`:** When closed, produces a fixed 489-char output:
   - All biases = neutral, confidence = 0.0
   - Clear Persian text: "بازار بسته است — تحلیل تکنیکال روی داده بسته معتبر نیست"
   - Skips ALL SMC/classic/macro imports and computation

3. **Summary gate in `_format_summary()`:** Early return when `market_closed=True`, producing identical output every time.

4. **Review script gate in `mt5_xau_review.py`:** `load_latest_snapshot()` now returns `None` if snapshot is >30min old, and `format_review_report(None)` returns the "بازار بسته" message.

5. **Oversight cron prompt updated:** If output contains "بازار بسته", `[SILENT]` — no analysis, no panic, no delivery.

**Result:** All cron outputs are now IDENTICAL and CONSISTENT during closed market. No more contradictory analyses. The pattern is reusable for any automated system with LLM + cron: always gate heavy analysis behind a freshness check.
