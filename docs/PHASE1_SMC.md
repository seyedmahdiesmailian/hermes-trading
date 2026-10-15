# Phase 1.5: SMC Engine Refactoring
## Started: 2026-10-15 (continuing session)

---

## 🎯 Target: Smart Money Concepts (SMC/ICT)

**File:** `legacy_v1/engines/smc.py` (1,032 lines)

**Complexity:** VERY HIGH
- Order blocks detection
- Fair value gaps (FVG)
- Liquidity zones
- Break of structure (BOS/CHoCH)
- Premium/discount arrays
- Multi-timeframe confluence

**Why Last:**
- ✅ Largest and most complex engine
- ✅ All other engines done (4/5 complete)
- ✅ Pattern established (92 tests proven)
- ✅ Most critical for trade quality

---

## 🔄 Refactoring Strategy

### Core Concepts:
1. **Order Blocks** - Institutional entry zones
2. **FVG (Fair Value Gaps)** - Imbalance areas
3. **Liquidity** - Stop hunts and sweeps
4. **Structure** - BOS/CHoCH detection
5. **Arrays** - Premium/discount price levels

### Domain Entities:
```python
@dataclass(frozen=True)
class OrderBlock:
    price: float
    side: str  # bullish, bearish
    strength: float
    timeframe: str
    
@dataclass(frozen=True)
class FairValueGap:
    top: float
    bottom: float
    side: str
    mitigated: bool
    
@dataclass(frozen=True)
class LiquidityZone:
    level: float
    zone_type: str  # equal_highs, equal_lows
    swept: bool
    
@dataclass(frozen=True)
class StructureShift:
    shift_type: str  # BOS, CHoCH
    price: float
    confidence: float
```

---

## ⏱️ Timeline

**Target: 5-6 hours total**
- Domain entities: 1 hour
- Service layer: 2-3 hours (most complex)
- Tests: 1.5 hours
- Adapter: 30 minutes

---

**Status:** 🟢 Starting now
**Current test count:** 92/92 ✅
**Goal:** 110+ tests after SMC
