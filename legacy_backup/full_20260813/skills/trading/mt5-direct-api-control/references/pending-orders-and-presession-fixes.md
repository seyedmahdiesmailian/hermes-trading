# Pending Orders and Pre-Session Fixes

Session-captured lessons from 2026-08-10 XAUUSD automation session.

## Pending Orders (buy_stop/sell_stop/buy_limit/sell_limit)

### Problem
Cron-based trading systems wake every 15 minutes. A good setup can appear and disappear between ticks. Market-only execution misses these opportunities.

### Solution
Added pending order support to `mt5_direct.py`:
- `build_pending_request()` — builds TRADE_ACTION_PENDING request
- `place_pending_order()` — validates with order_check then sends
- `cancel_pending_order()` — TRADE_ACTION_REMOVE by ticket
- `list_pending_orders()` — reads mt5.orders_get() with type mapping

### CLI Commands
```
python mt5_direct.py pending XAUUSD BUY_STOP 4340.00 0.01 4330.00 4350.00 "Hermes breakout"
python mt5_direct.py pending XAUUSD SELL_STOP 4320.00 0.01 4330.00 4310.00 "Hermes breakdown"
python mt5_direct.py pending XAUUSD BUY_LIMIT 4325.00 0.01 4315.00 4345.00 "Hermes pullback"
python mt5_direct.py cancel_order TICKET
python mt5_direct.py orders XAUUSD
```

### MT5 Order Type Constants
- `ORDER_TYPE_BUY_STOP` = 4 (entry above current price)
- `ORDER_TYPE_SELL_STOP` = 5 (entry below current price)
- `ORDER_TYPE_BUY_LIMIT` = 2 (entry below current price)
- `ORDER_TYPE_SELL_LIMIT` = 3 (entry above current price)
- Action: `TRADE_ACTION_PENDING` (5) for placing, `TRADE_ACTION_REMOVE` (8) for canceling
- Filling: `ORDER_FILLING_RETURN` works for pending orders on Capitalxtend

### Verified
- Buy stop placed at 4340.00 with SL=4330.00 TP=4350.00 → retcode 10009 (DONE)
- Cancel by ticket → retcode 10009 (DONE)
- `orders XAUUSD` correctly lists pending orders with type/volume/price/sl/tp

## OpenBLAS Memory Crash Fix

### Problem
`mt5_xau_presession.py` crashed with: `OpenBLAS error: Memory allocation still failed after 10 retries, giving up`

### Root Cause
Not a RAM shortage (8GB total, 3.8GB free). Thread collision: OpenBLAS defaults to using all CPU cores for BLAS operations. When MT5 terminal + numpy + pandas run simultaneously, threads compete for memory allocation and fail after 10 retries.

### Fix
```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 python mt5_xau_presession.py
```

Set these env vars in cron job scripts or any Python script that processes large MT5 candle arrays through numpy. The script then runs successfully in ~5 seconds.

### Application
Add to cron job scripts that call MT5 data collection:
```bash
#!/bin/bash
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
python mt5_xau_presession.py
```

## Grade C Zero-Risk Over-Filtering Bug

### Problem
System placed 15 consecutive WAIT decisions over an entire trading day (10:07 to 15:45) with zero trades executed.

### Root Cause Chain
1. `setup_grade = "B" if merged.get("confidence", 0) > 0.6 else "C"` — only two grades, threshold too high
2. `grade_multiplier = {"A": 1.0, "B": 0.6, "C": 0.0}` — grade C = zero risk
3. `risk_pct = 0` → `trade_allowed = False` → Hermes always WAITed
4. Confidence never exceeded 0.333 all day → always grade C → always blocked

### Fix (3 patches)
1. **mt5_xau_decision_collector.py**: Three-tier grading instead of binary:
   ```python
   if conf > 0.6: grade = "A"
   elif conf > 0.35: grade = "B"
   else: grade = "C"
   ```
2. **mt5_account_risk.py**: Grade C multiplier from 0.0 to 0.3:
   ```python
   "C": 0.3,  # was 0.0
   ```
3. **mt5_xau_defcon.py**: DEFCON YELLOW risk_override from 0.5 to 0.75

### Lesson
**Hermes must be the brain, code must be the apprentice.** When `trade_allowed=False` came from code, Hermes blindly accepted WAIT without applying its own trader judgment. The code's gate became the decision-maker instead of a data input. Hermes should evaluate R:R, structure, and context independently — even when code says "allowed" or "not allowed."
