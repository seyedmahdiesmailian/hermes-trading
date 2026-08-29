# Hermes Must Be the Brain, Code the Apprentice

Session-captured lesson from 2026-08-10 XAUUSD automation session.

## The Problem

Hermes was designed as the "brain" and code as the "apprentice/tool." But in practice, the relationship inverted:

1. Code computed `trade_allowed = False` (grade C = 0.0 risk multiplier)
2. Hermes blindly accepted the code's verdict: "If code says not allowed, I WAIT"
3. This happened 15 times in a row (10:07 to 15:45) — zero trades all day
4. The market moved from ~4320 to ~4344 (a clear bullish trend) and Hermes missed it entirely

## Root Cause

The decision pipeline had code making the **decision**, not just providing **data**:

```
WRONG:  Code says trade_allowed=False → Hermes says WAIT (code decided)
RIGHT:  Code says confidence=0.33, OTE zone, R:R=0.6 → Hermes evaluates independently → Hermes decides
```

The code's `trade_allowed` gate became the decision-maker. Hermes deferred to it instead of applying independent trader judgment.

## The Fix

### Code Fix (3 patches)
1. **Grade logic** — three-tier (A/B/C) instead of binary (B/C):
   ```python
   if conf > 0.6: grade = "A"
   elif conf > 0.35: grade = "B"
   else: grade = "C"
   ```
2. **Grade C multiplier** — from 0.0 to 0.3 (allow reduced risk, not zero)
3. **DEFCON YELLOW risk_override** — from 0.5 to 0.75

### Behavioral Fix (Hermes-side)
Hermes must independently evaluate these factors regardless of what code says:
- **R:R (reward-to-risk)** — is it at least 1.5:1?
- **Multi-TF alignment** — do H1, M15, M5 agree?
- **Price position in range** — discount (buy zone) or premium (sell zone)?
- **Killzone timing** — is a high-liquidity session active?
- **Divergence** — does M5 RSI diverge from price?

If code says `trade_allowed=True` but R:R is bad → Hermes should still WAIT.
If code says `trade_allowed=False` but Hermes sees a strong setup → Hermes should override (after the code fix, this path is less likely, but the principle stands).

## Key Principle

**Code provides data. Hermes makes decisions. Code executes.**

The decision flow must be:
```
Code collects data → Code provides analysis hints → Hermes evaluates independently → Hermes decides → Code executes
```

NOT:
```
Code collects data → Code decides trade_allowed → Hermes accepts → WAIT/ENTER
```

## User Feedback

User (Mehdi) was frustrated: "چرا بیش از حد محتاطی؟" (Why are you being too cautious?)

He explicitly stated: "قرار بود کد شاگردت باشه و تمام کارا خودت بکنی" (The plan was for code to be your apprentice and you do everything yourself)

This is a first-class design principle, not a one-time correction. The autonomous trading agent must always exercise independent judgment — code gates are inputs, not decisions.
