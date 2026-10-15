# Phase 1: Engine Refactoring
## Week 3-4 (Current)

---

## 🎯 Goals

1. Refactor one legacy engine as **proof of concept**
2. Establish refactoring patterns
3. Integrate with Database layer
4. Maintain backward compatibility
5. Add comprehensive tests

---

## 📋 Target: DEFCON System

**Why DEFCON first?**
- ✅ Small (197 lines)
- ✅ Critical safety system
- ✅ Clear responsibilities
- ✅ Well-isolated logic
- ✅ Easy to test

**Current Issues:**
- ❌ Mixed concerns (state + logic)
- ❌ Hardcoded values
- ❌ JSON file I/O scattered
- ❌ No tests
- ❌ Difficult to extend

---

## 🔄 Refactoring Strategy

### Step 1: Extract Domain Model (30 min)
```python
# brain/domain/entities/defcon.py
class DefconLevel(Enum):
    GREEN = 1   # Normal
    YELLOW = 2  # Caution
    ORANGE = 3  # Warning
    RED = 4     # Critical
    BLACK = 5   # Kill switch

@dataclass
class DefconState:
    level: DefconLevel
    loss_streak: int
    daily_loss_pct: float
    kill_switch_active: bool
    risk_multiplier: float
    updated_at: int
```

### Step 2: Create Service Layer (45 min)
```python
# brain/application/services/defcon_service.py
class DefconService:
    def __init__(self, db: Database):
        self.db = db
    
    def evaluate_level(self, account_state: Dict) -> DefconLevel:
        """Calculate appropriate DEFCON level."""
        pass
    
    def apply_restrictions(self, level: DefconLevel) -> Dict:
        """Get trading restrictions for level."""
        pass
    
    def check_kill_switch(self) -> bool:
        """Check if kill switch should activate."""
        pass
```

### Step 3: Add Repository (20 min)
```python
# brain/infrastructure/persistence/defcon_repository.py
class DefconRepository:
    def __init__(self, db: Database):
        self.db = db
    
    def get_state(self) -> DefconState:
        return self.db.get_risk_state()
    
    def save_state(self, state: DefconState):
        self.db.update_risk_state(state)
```

### Step 4: Write Tests (1 hour)
```python
# tests/test_defcon.py
def test_defcon_level_calculation():
    # Green: normal conditions
    # Yellow: 2 losses
    # Orange: 3 losses or -3% daily
    # Red: 4 losses or -5% daily
    # Black: -10% daily
    pass

def test_risk_multipliers():
    # GREEN: 1.0x
    # YELLOW: 0.5x
    # ORANGE: 0.25x
    # RED: 0.0x (no trades)
    pass

def test_kill_switch_activation():
    pass
```

### Step 5: Create Adapter (30 min)
```python
# legacy_v1/adapters/defcon_adapter.py
# Maintains backward compatibility
class DefconAdapter:
    """Adapter for legacy code to use new DefconService."""
    
    def __init__(self):
        self.service = DefconService(get_db())
    
    def get_level(self) -> str:
        """Legacy interface."""
        level = self.service.get_current_level()
        return level.name  # 'GREEN', 'YELLOW', etc.
```

### Step 6: Integration (30 min)
- Update legacy_v1/engines/orchestrator.py to use adapter
- Verify existing code still works
- Add logging

---

## ✅ Acceptance Criteria

- [ ] Domain entities defined
- [ ] Service layer implemented
- [ ] Repository connected to Database
- [ ] 10+ unit tests (100% coverage)
- [ ] Adapter maintains backward compatibility
- [ ] Legacy code uses new system
- [ ] All existing tests pass
- [ ] Documentation updated
- [ ] Code pushed to GitHub

---

## 📊 Success Metrics

- **Code Quality:** Separation of concerns ✅
- **Testability:** 100% coverage ✅
- **Maintainability:** Easy to extend ✅
- **Reliability:** No regressions ✅
- **Performance:** No slowdown ✅

---

## 🔄 Lessons for Next Engines

This refactor establishes patterns for:
- risk.py (similar to defcon)
- learning.py (state management)
- context.py (market analysis)
- smc.py (larger, complex)

---

## ⏱️ Timeline

- **Hour 1:** Domain model + Repository
- **Hour 2:** Service layer
- **Hour 3:** Tests
- **Hour 4:** Adapter + Integration

**Total: ~4 hours**

---

**Started:** 2026-10-15 18:45  
**Target:** 2026-10-15 22:45  
**Status:** 🟢 In Progress
