# Phase 1.2: Risk Engine Refactoring
## Started: 2026-10-15 19:30

---

## 🎯 Target: Risk Management System

**File:** `legacy_v1/engines/risk.py` (273 lines)

**Why Second:**
- ✅ Similar to DEFCON (state management)
- ✅ Simple, clear logic
- ✅ Database benefits immediate
- ✅ Critical for safety

**Current Issues:**
- ❌ Mixed concerns (state + calculation)
- ❌ Dict-based (no type safety)
- ❌ Manual JSON file handling
- ❌ No tests
- ❌ Hard to extend

---

## 🔄 Refactoring Plan

### Step 1: Domain Entities (30 min)
```python
# brain/domain/entities/risk.py

@dataclass(frozen=True)
class RiskState:
    loss_streak: int
    win_streak: int
    daily_pnl: float
    daily_loss_pct: float
    max_daily_loss_hit: bool
    risk_multiplier: float
    updated_at: int

@dataclass(frozen=True)
class PerformanceState:
    balance: float
    equity: float
    margin_level: float
    daily_pnl: float
    weekly_pnl: float
    loss_streak: int
    win_streak: int
    recent_closed: list[dict]
```

### Step 2: Service Layer (1 hour)
```python
# brain/application/services/risk_service.py

class RiskService:
    def __init__(self, db: Database):
        self.db = db
    
    def compute_performance_state(self, account, deals) -> PerformanceState:
        # Calculate streaks, P&L, etc.
        pass
    
    def update_risk_multiplier(self, state: RiskState) -> float:
        # Adjust risk based on performance
        pass
    
    def check_daily_loss_limit(self, daily_pnl, balance) -> bool:
        # Kill switch logic
        pass
```

### Step 3: Tests (1 hour)
- Streak calculation
- Risk multiplier logic
- Daily loss limits
- Performance state

### Step 4: Adapter + Integration (1 hour)
- Backward compatible adapter
- Update callers
- Verify

---

## ⏱️ Timeline

- **Start:** 19:30
- **Domain:** 19:30-20:00 (30 min)
- **Service:** 20:00-21:00 (60 min)
- **Tests:** 21:00-22:00 (60 min)
- **Integration:** 22:00-22:30 (30 min)
- **Target completion:** 22:30

**Total: 3 hours**

---

**Status:** 🟢 Starting now
