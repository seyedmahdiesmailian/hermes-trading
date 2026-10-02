# Hybrid Brain-Apprentice Architecture v4

Implemented 2026-08-08 for Mehdi's XAUUSD trading system.

## Problem
Previous architecture: code made ALL decisions (runtime.py), Hermes was a passive overseer checking every 2 hours. The user explicitly wanted Hermes to be the brain — managing positions from open to close, learning from mistakes, updating the code.

## Solution: Three-Layer Architecture

### Layer 1: Hermes (LLM) — The Brain
- Cron fires every 15 min with decision collector output
- Reads full market context: SMC + classic + account + positions
- Decides: wait / enter / modify / close / close_partial
- Records rationale in decision journal (Persian)
- Updates heartbeat after every decision
- Cron: `549e6796fd3e` (Hermes XAUUSD Decision Loop)

### Layer 2: Code — The Apprentice
- Decision collector (`mt5_xau_decision_collector.py`): gathers data + runs analysis
- `mt5_direct.py`: executes decisions (open/close/modify/partial) — no autonomy
- SMC engine (`mt5_xau_smc.py`): 17 ICT concepts, M15+H1
- Classic analysis (`mt5_xau_context.py`): bias, regime, value zone
- Old runtime (`a30c74242663`): paused as fallback backup

### Layer 3: Heartbeat & Fallback
- `mt5_xau_heartbeat.py` tracks last Hermes decision timestamp
- `< 30 min`: hermes_active → Hermes decides, full risk (×1.0)
- `30-120 min`: hermes_degraded → Hermes + conservative (×0.75)
- `> 120 min`: code_fallback → resume paused runtime cron (×0.5)
- Heartbeat checked every tick by decision collector

## Decision Loop Flow

```
cron every 15min
  → collector.py runs
    → MT5: M15, H1, H4, tick, account, positions
    → Classic: bias, regime, value zone, ATR, zones
    → SMC: 17 concepts, confidence, structure (M15+H1)
    → Merge: bias, confidence, action hint
    → Risk: policy, budget, trade_allowed
    → Heartbeat: mode, minutes_since_last
    → Output: human-readable summary + JSON
  → Hermes (LLM) reads output
    → Checks: market open? positions? risk allowed?
    → Decides: wait | enter_buy | enter_sell | modify | close | close_partial
    → If action ≠ wait: executes via mt5_direct.py
    → Records decision in journal
    → Updates heartbeat
    → Delivers Persian report (silent on wait+no-change)
```

## Decision Journal

`mt5_xau_journal.py` stores entries at `trading/xau_journal/`.
Each entry: timestamp, decision_by (hermes/code_fallback), market_snapshot,
decision {action, reasoning, risk_check}, execution, outcome, lessons.

### Weekly Learning Pass Pattern
1. Read all journal entries from past week
2. Classify exits: SL hit, TP hit, managed close, early exit
3. Find failing patterns (e.g. "3 range setups stopped out")
4. Write lessons into journal
5. Patch code thresholds/weights/guardrails
6. Resume: apprentice is now smarter

## Files Created
- `mt5_xau_decision_collector.py` — data collection + analysis (16.5 KB)
- `mt5_xau_heartbeat.py` — hermes presence tracking (4.5 KB)
- `mt5_xau_journal.py` — decision recording + weekly review (5.8 KB)

## Cron Configuration
| ID | Name | Role | Schedule | Status |
|---|---|---|---|---|
| 549e6796fd3e | Hermes XAUUSD Decision Loop | Brain (LLM decides) | every 15m | ACTIVE |
| a30c74242663 | Gold XAUUSD Auto Trader | Fallback (code-based) | every 15m | PAUSED |
| dcbb59fbf158 | Hermes XAUUSD Oversight | Health monitor | every 120m | ACTIVE |

## Key Decisions
1. **Code runs collector, Hermes decides.** Separation of concerns: calculation → code, judgment → LLM.
2. **Heartbeat, not hard switch.** Graceful degradation: Hermes slow → conservative; Hermes gone → code takes over.
3. **Journal as learning substrate.** Every decision recorded with rationale → weekly review → code improvement.
4. **Code as apprentice, not peer.** LLM patches code weekly; code doesn't override LLM.
5. **Old runtime preserved as fallback.** Paused cron can be resumed if LLM goes offline for > 2h.
