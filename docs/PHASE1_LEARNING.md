# Phase 1.3: Learning Engine Refactoring
## Started: 2026-10-15 18:20

---

## 🎯 Target: Adaptive Learning System

**File:** `legacy_v1/engines/learning.py` (568 lines)

**Complexity:** HIGH
- Journal management (CSV operations)
- Trade analysis (stats per grade/session/side)
- Parameter adjustments (risk, grade, RR)
- State persistence

**Why Third:**
- ✅ More complex than DEFCON/Risk
- ✅ Database will simplify CSV logic
- ✅ Critical for adaptive behavior
- ✅ Foundation ready (DB + tests proven)

---

## 🔄 Refactoring Strategy

### Core Functions:
1. **journal()** - Sync MT5 deals → journal CSV
2. **analyze()** - Compute stats per dimension
3. **adjustments()** - Propose parameter changes
4. **apply()** - Save learning state

### Domain Entities:
```python
@dataclass(frozen=True)
class JournalEntry:
    ticket: int
    position_id: str
    side: str
    volume: float
    profit: float
    commission: float
    swap: float
    setup_grade: str
    session: str
    
@dataclass(frozen=True)
class TradeStatistics:
    total_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    profit_factor: float
    
@dataclass(frozen=True)
class LearningAdjustments:
    risk_multiplier: float
    min_grade: str
    rr_floor: float
    reason: str
```

---

## ⏱️ Timeline

- **Start:** 18:20
- **Domain:** 18:20-18:50 (30 min)
- **Service:** 18:50-20:00 (70 min)
- **Tests:** 20:00-21:00 (60 min)
- **Adapter:** 21:00-21:30 (30 min)
- **Target:** 21:30

**Total: 3 hours** (longer due to complexity)

---

**Status:** 🟢 Starting now
