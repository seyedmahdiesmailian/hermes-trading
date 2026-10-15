# Phase 2.1: Wire Adapters to hermes_runtime.py
**Date:** 2026-10-15
**File:** hermes_runtime.py (1,431 lines)

---

## 🎯 Current State

### Old Engine Imports (to be replaced):
```python
from engines.context import build_plan_context                    # Line 20
from engines.smc import smc_analyse, merge_smc_with_classic       # Line 22
from engines.risk import assess_account_policy, compute_performance_state  # Line 26
```

### Note:
- DEFCON already using adapter in `auto_executor.py` ✅
- Learning imports in `auto_executor.py` (line 168) - needs adapter

---

## 🔧 Replacement Strategy

### Step 1: Add Adapter Imports (TOP of file, after old imports)
```python
# REFACTORED (2026-10-15): Use new adapters
from legacy_v1.adapters.risk_adapter import RiskAdapter
from legacy_v1.adapters.context_adapter import ContextAdapter  
from legacy_v1.adapters.smc_adapter import SMCAdapter
```

### Step 2: Initialize Adapters (at module level)
```python
# Initialize refactored service adapters
_risk_adapter = RiskAdapter()
_context_adapter = ContextAdapter()
_smc_adapter = SMCAdapter()
```

### Step 3: Replace Function Calls

#### Risk Engine:
```python
# OLD:
assess_account_policy(balance, equity, ...)
compute_performance_state(deals, ...)

# NEW:
_risk_adapter.assess_account_policy(balance, equity, ...)
_risk_adapter.compute_performance_state(deals, ...)
```

#### Context Engine:
```python
# OLD:
build_plan_context(rows_m5, rows_m15, ...)

# NEW:
_context_adapter.build_plan_context(rows_m5, rows_m15, ...)
```

#### SMC Engine:
```python
# OLD:
smc_analyse(rows, h1_rows, now)
merge_smc_with_classic(classic_ctx, smc_result)

# NEW:
_smc_adapter.analyze_smc(rows, h1_rows, now)
_smc_adapter.merge_smc_with_classic(classic_ctx, smc_result)
```

---

## 📋 Execution Steps

1. ✅ Verify all adapters exist and have correct methods
2. ⚪ Replace imports in hermes_runtime.py
3. ⚪ Initialize adapters
4. ⚪ Replace all function calls (risk first)
5. ⚪ Test: python3 -m py_compile hermes_runtime.py
6. ⚪ Run integration tests
7. ⚪ Commit with rollback plan
8. ⚪ Monitor production for 1 hour
9. ⚪ If stable, proceed to next engine

---

## ⚠️ Safety Checklist

- [ ] All adapters have matching method signatures
- [ ] Outputs are dict-based (legacy compatible)
- [ ] No new dependencies introduced
- [ ] Rollback script ready (git revert)
- [ ] Production monitoring active
- [ ] Test suite passing before changes
- [ ] Test suite passing after changes

---

## 🎯 Success Criteria

✅ hermes_runtime.py compiles
✅ All tests passing (124/124)
✅ Production stable (no errors in logs)
✅ Same behavior as before (output comparison)
