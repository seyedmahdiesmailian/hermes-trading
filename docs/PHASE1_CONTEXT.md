# Phase 1.4: Context Engine Refactoring
## Started: 2026-10-15 19:45

---

## 🎯 Target: Market Context Analysis

**File:** `legacy_v1/engines/context.py` (392 lines)

**Complexity:** MEDIUM-HIGH
- Market structure analysis (HTF trend, support/resistance)
- Multi-timeframe context (H4, H1, M15)
- Supply/demand zones
- Trend classification
- Session-aware analysis

**Why Fourth:**
- ✅ More complex than DEFCON/Risk/Learning
- ✅ Foundation ready (DB + 73 tests proven)
- ✅ Critical for plan quality assessment
- ✅ Dependencies on market data

---

## 🔄 Refactoring Strategy

### Core Functions:
1. **build_context()** - Multi-timeframe analysis
2. **detect_trend()** - HTF trend classification
3. **find_zones()** - Support/resistance levels
4. **assess_structure()** - Market structure state

### Domain Entities:
```python
@dataclass(frozen=True)
class TrendState:
    direction: str  # bullish, bearish, ranging
    strength: float
    htf_aligned: bool
    
@dataclass(frozen=True)
class PriceZone:
    level: float
    zone_type: str  # support, resistance, demand, supply
    strength: float
    touches: int
    
@dataclass(frozen=True)
class MarketStructure:
    trend: TrendState
    key_levels: list[PriceZone]
    bias: str
    
@dataclass(frozen=True)
class MarketContext:
    h4_structure: MarketStructure
    h1_structure: MarketStructure
    m15_structure: MarketStructure
    session: str
    volatility: float
```

---

## ⏱️ Timeline

- **Start:** 19:45
- **Domain:** 19:45-20:15 (30 min)
- **Service:** 20:15-21:30 (75 min)
- **Tests:** 21:30-22:30 (60 min)
- **Adapter:** 22:30-23:00 (30 min)
- **Target:** 23:00

**Total: 3.25 hours**

---

**Status:** 🟢 Starting now
