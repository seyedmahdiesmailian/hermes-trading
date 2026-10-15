# Phase 2: Integration & Wiring
**Started:** 2026-10-15
**Status:** 🟢 In Progress

---

## 🎯 Goal

Connect refactored engines to production system:
- Wire new services into `legacy_v1/engines/auto_executor.py`
- Replace old engine calls with adapter calls
- Maintain 100% backward compatibility
- Zero downtime deployment

---

## 📋 Strategy

### Current State:
```
legacy_v1/engines/auto_executor.py (714 lines)
├── Imports old engines directly:
│   ├── from engines import defcon
│   ├── from engines import risk
│   ├── from engines import learning
│   ├── from engines import context
│   └── from engines import smc
└── Calls old functions:
    ├── defcon.compute_insights(...)
    ├── risk.recommend_risk_budget(...)
    ├── learning.propose_adjustments(...)
    ├── context.build_plan_context(...)
    └── smc.analyze_smc(...)
```

### Target State:
```
legacy_v1/engines/auto_executor.py
├── Imports adapters:
│   ├── from legacy_v1.adapters.defcon_adapter import DefconAdapter
│   ├── from legacy_v1.adapters.risk_adapter import RiskAdapter
│   ├── from legacy_v1.adapters.learning_adapter import LearningAdapter
│   ├── from legacy_v1.adapters.context_adapter import ContextAdapter
│   └── from legacy_v1.adapters.smc_adapter import SMCAdapter
└── Calls new services through adapters:
    ├── defcon_adapter.compute_insights(...)
    ├── risk_adapter.recommend_risk_budget(...)
    ├── learning_adapter.propose_adjustments(...)
    ├── context_adapter.build_plan_context(...)
    └── smc_adapter.analyze_smc(...)
```

---

## 🔧 Tasks

### 2.1 Prepare auto_executor.py
- [ ] Read and analyze current imports
- [ ] Map all engine function calls
- [ ] Identify state dependencies
- [ ] Document data flow

### 2.2 Wire Adapters (One by One)
- [ ] 2.2.1: Replace DEFCON calls
- [ ] 2.2.2: Replace Risk calls
- [ ] 2.2.3: Replace Learning calls
- [ ] 2.2.4: Replace Context calls
- [ ] 2.2.5: Replace SMC calls

### 2.3 Verification
- [ ] Run integration tests
- [ ] Compare outputs (old vs new)
- [ ] Monitor production for 24h
- [ ] Rollback plan ready

### 2.4 Cleanup
- [ ] Remove old engine imports
- [ ] Archive legacy engines
- [ ] Update documentation

---

## ⚠️ Safety Rules

1. **One engine at a time** - Never replace multiple engines in one commit
2. **Test after each change** - Run full test suite
3. **Compare outputs** - Old vs new must match exactly
4. **Keep rollback ready** - Git revert must work instantly
5. **Monitor production** - Watch for any anomalies

---

## 📊 Progress

| Engine | Status | Commit | Tests | Production |
|--------|--------|--------|-------|------------|
| DEFCON | ⚪ TODO | - | - | - |
| Risk | ⚪ TODO | - | - | - |
| Learning | ⚪ TODO | - | - | - |
| Context | ⚪ TODO | - | - | - |
| SMC | ⚪ TODO | - | - | - |

---

## 🎯 Success Criteria

✅ All adapters wired into auto_executor
✅ All tests passing
✅ Production stable for 48h
✅ No performance degradation
✅ Old engines archived (not deleted)
