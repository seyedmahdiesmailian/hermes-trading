# Grade-C Zero-Risk Over-Filtering Bug

Session-captured lesson from 2026-08-10 XAUUSD automation session.

## The Bug

The account-aware risk system had a critical over-filtering bug that caused zero trades across an entire trading day.

### How It Worked

1. `mt5_xau_decision_collector.py` computed setup grade:
   ```python
   setup_grade = "B" if merged.get("confidence", 0) > 0.6 else "C"
   ```
   Only two grades: B (if confidence > 0.6) or C (everything else).

2. `mt5_account_risk.py` mapped grades to risk multipliers:
   ```python
   grade_multiplier = {"A": 1.0, "B": 0.6, "C": 0.0}
   ```
   Grade C = 0.0 → risk_pct = 0 → trade_allowed = False.

3. On the day in question, confidence never exceeded 0.333 → always grade C → always risk = 0 → always WAIT.

### The Result
15 consecutive WAIT decisions from 10:07 to 15:45. Zero trades. Market moved from ~4320 to ~4344 (clear bullish trend). Complete opportunity cost.

## The Fix (3 Patches)

### Patch 1: Three-tier grading
File: `mt5_xau_decision_collector.py`
```python
# Before:
setup_grade = "B" if merged.get("confidence", 0) > 0.6 else "C"

# After:
conf = merged.get("confidence", 0)
if conf > 0.6:
    setup_grade = "A"
elif conf > 0.35:
    setup_grade = "B"
else:
    setup_grade = "C"
```

### Patch 2: Grade C allows reduced risk, not zero
File: `mt5_account_risk.py`
```python
# Before:
grade_multiplier = {"A": 1.0, "B": 0.6, "C": 0.0}

# After:
grade_multiplier = {"A": 1.0, "B": 0.6, "C": 0.3}
```

### Patch 3: DEFCON YELLOW less restrictive
File: `mt5_xau_defcon.py`
```python
# Before:
result["risk_override"] = 0.5  # Cut risk in half

# After:
result["risk_override"] = 0.75  # Allow more trades under YELLOW
```

## Lesson

**All-day WAIT with zero trades is a bug, not "being conservative."**

The `account-aware-trading-risk` skill already warns about this in its pitfalls:
> "Do not make filters so strict that the system undertrades and misses good setups."

But the concrete implementation violated this principle. The fix ensures:
- Grade C gets 0.3× risk (not 0.0)
- DEFCON YELLOW gets 0.75× risk (not 0.5×)
- Confidence threshold for grade B is 0.35 (not 0.6)

After the fix, the same market conditions produced `trade_allowed=True` with `risk_usd=$4.55` where it previously returned `trade_allowed=False` with `risk_usd=$0`.

## Verification
- 204/204 tests passed after all 3 patches
- Live test confirmed `trade_allowed=True, risk_usd=$4.55, risk_pct=0.0034`
