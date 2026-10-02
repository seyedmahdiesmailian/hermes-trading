# SMC/ICT/RTM Analysis Architecture

## Files

| File | Role |
|------|------|
| `mt5_xau_smc.py` | SMC engine: 7 basic + 9 advanced concepts (since 2026-08-08) |
| `mt5_xau_context.py` | Classic analysis: value zones, regime, bias |
| `mt5_xau_runtime.py` | Orchestrator: calls both, merges, builds plan |

## Concepts

### Basic (7 — v1)
OB, FVG, Liquidity Sweep, Market Structure, Premium/Discount, Killzone, POI Grading

### Advanced (9 — v2, 2026-08-08)
Breaker Block, Rejection Block, OTE Zone, Power of 3, Turtle Soup, Silver Bullet, Session Liquidity, Volume Imbalance.

See `mt5-forex-automation` skill → `references/smc-ict-rtm-engine.md` for full function table and TDD pitfalls.

## Merge Flow (in `_build_live_plan`, v2.1 2026-08-08)

```
m15, h1, h4 = _rows(...)
              │
              ├─ build_plan_context(m15, h1, h4, session)  → classic ctx
              └─ smc_analyse(m15, now=now, h1_rows=h1)      → smc result (v2: H1 OB/FVG/structure)
                          │
                  merge_smc_with_classic(classic, smc)
                          │
              # Range guard: if classic regime=range, force neutral
              if classic_regime == "range" and merged["bias"] != "neutral":
                  ctx["bias"] = "neutral"
                  merged["bias"] = "neutral"
                  merged["confidence"] = min(merged["confidence"], 0.3)
                  merged["action"] = "wait"
              else:
                  ctx["bias"] = merged["bias"]
              ctx["quality"]["smc_confidence"] = merged["confidence"]
              ctx["quality"]["smc_poi"] = merged["smc_source"]["poi"]
              ctx["setdefault"]("context", {})
              ctx["context"]["smc"] = smc   # includes 8 advanced concepts
              ctx["context"]["merged"] = merged
                          │
                  build_plan_from_context(ctx)
```

## SMC Concept Coverage (v2.1)

| Layer | Concepts | Status |
|-------|----------|--------|
| Basic (v1) | OB, FVG, Liq Sweep, Structure, P/D, Killzone, POI | ✅ Active |
| Advanced (v2) | Breaker, Rejection, OTE, Power of 3, Turtle Soup, Silver Bullet, Session Liq, Volume Imbalance | ✅ Active since 2026-08-08 |
| Multi-TF (v2.1) | H1 OB, H1 FVG, H1 Structure, H1-based P/D swing | ✅ Active since 2026-08-08 |

Previously the 8 advanced concepts were defined but not called in `smc_analyse()` — they were dead code (~47% of the engine). All are now wired and producing live output.

## Merge Confidence Scaling (v2.1)

| Scenario | Classic Bias | SMC Bias | SMC Factor | Example (c=0.87) |
|----------|-------------|----------|------------|--------------------|
| Classic neutral | neutral | bullish | 0.9 | 0.78 |
| Both agree | bullish | bullish | w×0.7 | 0.43 |
| Opposing | bullish | bearish | w×0.4 | 0.24 |

## Killzone Sessions (UTC)

| Session | Start | End | Weight |
|---------|-------|-----|--------|
| Asia | 00:00 | 05:00 | 0.60 |
| London | 07:00 | 09:00 | 1.00 |
| New York | 12:00 | 14:00 | 1.00 |
| Dead (all else) | — | — | 0.00 → dampen ×0.3 |

## Test Suite

`tests/test_mt5_xau_smc.py` — 53 tests covering all 16 SMC concepts (7 basic + 9 advanced).
Run: `pytest tests/test_mt5_xau_smc.py -q`

Total suite: 204 tests (53 SMC + 151 classic/management), all green as of 2026-08-08.

## Known Limitations

1. ~~SMC uses M15 swing levels for P/D. Higher-TF swings not fed in.~~ → Fixed v2.1: H1 swing used for P/D when available.
2. ~~No multi-timeframe SMC (e.g., H1 OB confirmed by M15 trigger).~~ → Partially fixed v2.1: H1 OBs/FVGs/structure computed and merged.
3. Killzone doesn't account for DST transitions — fixed UTC windows.
4. SMC has 0 real-market track record as of 2026-08-08.
5. OTE zone returns a `lambda in_zone(price)` that must be stripped before JSON serialization (stripped in `smc_analyse()`).

## Hermes Oversight Layer

The user expects Hermes to act as **overseer**, not just run code. Architecture:

```
mt5_xau_runtime.py (_build_live_plan)
  → after plan saved: save_review_snapshot(plan, smc, merged, now)
    → writes to trading/xau_plan/review_snapshots/latest_snapshot.json
      (full SMC detail: OB, FVG, structure, confidence, POI, breaker, OTE, etc.)
        ↓
Cron "Hermes XAUUSD Oversight Review" (every 2h)
  → runs python mt5_xau_review.py
    → loads latest_snapshot.json
    → formats as Persian review report
    → Hermes evaluates: bias agreement, POI validity, structure, killzone
    → responds in Persian: تأیید or flags issues
```

### Files
| File | Role |
|------|------|
| `mt5_xau_review.py` | Saves/loads/formats analysis snapshots for Hermes review |
| `review_snapshots/latest_snapshot.json` | Current analysis snapshot |
| `review_snapshots/snapshot_YYYYMMDD_HHMMSS.json` | Historical snapshots (kept 50 max) |
| Cron `bc6840226bad` | Every 2h: reads snapshot → Hermes reviews quality |

### Review Checklist (what Hermes evaluates)
- Bias agreement: SMC vs classic
- POI grade logic
- Killzone weight application
- Confidence sufficiency for entry
- Market structure correctness (BOS/CHoCH)
- Order Block validity

### Pitfall
The review snapshot is saved inside `_build_live_plan` in the runtime. If the runtime runs a `monitor` step (no plan rebuild), no new snapshot is written — the oversight cron reads the last one. This is by design: review when analysis changes, not every tick. If the snapshot is more than 4 hours old and the market is open, that's a signal the runtime may be stuck in a monitor loop and needs attention.
