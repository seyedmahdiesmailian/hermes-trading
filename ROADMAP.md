# 🗺️ Hermes Trading - نقشه راه بازسازی
## از V1 Legacy به V1.5 Pragmatic

**تاریخ شروع:** 2026-10-15  
**وضعیت:** Phase 0 - تثبیت و پایه‌گذاری

---

## 🎯 استراتژی کلی: Strangler Fig Pattern

```
به جای rewrite کامل:
├─ V1 (Legacy) را تمیز کن
├─ Database مرکزی اضافه کن
├─ Monolith را به ماژول‌های مستقل تقسیم کن
└─ مرحله به مرحله refactor کن

نتیجه: V1.5 (Evolved V1) - کار می‌کنه + قابل نگهداری
```

---

## 📅 Timeline کلی

| Phase | مدت | وضعیت | توضیح |
|-------|-----|-------|-------|
| Phase 0 | هفته 1-2 | 🟢 در حال اجرا | تثبیت + Database |
| Phase 1 | هفته 3-4 | ⚪ بعدی | Refactor Engines |
| Phase 2 | هفته 5-8 | ⚪ منتظر | Service Extraction |
| Phase 3 | هفته 9-12 | ⚪ منتظر | Bridge بهبودیافته |
| Phase 4 | هفته 13-18 | ⚪ آینده | AI Signal Analyzer |

---

## Phase 0: تثبیت و پایه‌گذاری ✅
**هدف:** سیستم را stabilize کن + Database مرکزی

### ✅ انجام شد:
- [x] تحلیل کامل معماری فعلی
- [x] مستندسازی V1 و V2
- [x] طراحی Database Schema (SQLite)
- [x] پیاده‌سازی Database Wrapper
- [x] تست Database Layer

### 🔄 در حال انجام:
- [ ] Migration از JSON به Database
  - [ ] Plans migration
  - [ ] Trades migration
  - [ ] Signals migration
  - [ ] State migration
- [ ] Dual-write mode (JSON + DB)
- [ ] Verify data integrity

### 📋 TODO:
- [ ] Logging framework
- [ ] Monitoring dashboard
- [ ] Health check improvements

**Deliverable:** Database مرکزی کار می‌کنه، data migrate شده

---

## Phase 1: Refactor Core Engines 🔄
**هدف:** `legacy_v1/engines/` را تمیز کن

### استراتژی:
**نه rewrite، بلکه extract + simplify**

```
قبل:
legacy_v1/engines/
├── auto_executor.py (714 خط!) ❌
├── context.py (392 خط)
├── smc.py (1032 خط)
└── ... 28 ماژول دیگر

بعد:
core/
├── analysis/
│   ├── market_analyzer.py
│   ├── smc_analyzer.py
│   └── context_builder.py
├── decision/
│   ├── decision_engine.py
│   ├── validators.py
│   └── scoring.py
├── risk/
│   ├── risk_manager.py
│   ├── position_sizer.py
│   └── safety_checks.py
└── execution/
    ├── executor.py
    ├── order_builder.py
    └── trade_manager.py
```

### مراحل:
1. **Extract Analysis Logic**
   - `context.py` → `core/analysis/context_builder.py`
   - `smc.py` → `core/analysis/smc_analyzer.py`
   - Tests برای هرکدام

2. **Extract Decision Logic**
   - `auto_executor.evaluate_proposal()` → `core/decision/decision_engine.py`
   - جدا کردن 10+ checks به validators

3. **Extract Risk Management**
   - `risk.py` → `core/risk/risk_manager.py`
   - `defcon.py` → `core/risk/defcon_system.py`
   - `learning.py` → `core/risk/learning_engine.py`

4. **Extract Execution**
   - `auto_executor.execute_trade()` → `core/execution/executor.py`
   - `trade_management.py` → `core/execution/trade_manager.py`

### قوانین:
- ✅ هر extraction = یک commit جداگانه
- ✅ Tests قبل از merge
- ✅ Legacy code نگه داشته می‌شه (deprecated)
- ✅ Gradual cutover

**Duration:** 4-6 هفته  
**Deliverable:** Core modules تمیز + tested

---

## Phase 2: Service Extraction 🔮
**هدف:** ماژول‌های مستقل با API

### Services:

#### 1. **Scanner Service**
```python
services/scanner/
├── scanner.py          # Main scanner
├── analyzer.py         # Market analysis
└── api.py             # Internal REST API

API:
  POST /scan → {plan}
```

#### 2. **Signal Processor Service**
```python
services/signal_processor/
├── processor.py        # Signal processing
├── parser.py          # Message parser
├── validator.py       # Signal validation
└── api.py

API:
  POST /process-signal → {decision}
```

#### 3. **Position Manager Service**
```python
services/position_manager/
├── manager.py         # Position management
├── tracker.py        # MFE/MAE tracking
└── api.py

API:
  GET /positions → [positions]
  POST /manage/{ticket} → {action}
```

#### 4. **Risk Manager Service**
```python
services/risk_manager/
├── manager.py         # Risk management
├── defcon.py         # DEFCON system
├── learning.py       # Learning engine
└── api.py

API:
  GET /risk-state → {state}
  POST /evaluate → {allowed, reason}
```

### Communication:
- **Internal REST APIs** (Flask/FastAPI)
- همه services می‌توانن standalone run بشن
- هرکدام = یک systemd service

**Duration:** 4 هفته  
**Deliverable:** 4 services مستقل

---

## Phase 3: Bridge بهبودیافته 🌉
**هدف:** Real-time, Resilient, Reliable

### مشکلات فعلی:
- ❌ HTTP polling (not real-time)
- ❌ No automatic retry
- ❌ Single point of failure
- ❌ High latency

### راه‌حل:

#### 1. **WebSocket Connection**
```python
# به جای:
response = requests.post(url, ...)

# استفاده از:
import websocket
ws = websocket.WebSocket("ws://192.168.10.51:5050/stream")
```

**مزایا:**
- Real-time data stream
- Price updates instant
- Order status changes instant

#### 2. **Retry Logic**
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def execute_order(...):
    ...
```

#### 3. **Failover System**
```python
bridges = [
    "http://192.168.10.51:5050",  # Primary
    "http://192.168.10.52:5050",  # Secondary
    "http://192.168.10.53:5050",  # Tertiary
]

for bridge in bridges:
    try:
        return call(bridge)
    except:
        continue
```

#### 4. **Health Monitoring**
- Heartbeat every 5s
- Latency tracking
- Auto-reconnect on disconnect

**Duration:** 2 هفته  
**Deliverable:** Bridge قوی و real-time

---

## Phase 4: AI Signal Analyzer 🤖
**هدف:** Intelligence بالا برای signal processing

### مشکلات فعلی:
- ❌ Regex parser (شکننده)
- ❌ No credibility scoring
- ❌ No NLP
- ❌ Simple 4-check validation

### راه‌حل:

#### 1. **NLP Parser**
```python
from transformers import pipeline

class SignalParser:
    def __init__(self):
        self.ner = pipeline("ner", model="xlm-roberta-base")
    
    def parse(self, text: str) -> Signal:
        # NLP-based extraction
        entities = self.ner(text)
        ...
```

#### 2. **Credibility Scorer**
```python
class CredibilityScorer:
    def score(self, signal: Signal) -> float:
        # 1. Source reliability (track record)
        source_score = self.get_source_accuracy(signal.source)
        
        # 2. Signal quality
        quality_score = self.evaluate_geometry(signal)
        
        # 3. Market alignment
        alignment_score = self.check_market_context(signal)
        
        # 4. Historical performance
        history_score = self.check_similar_signals(signal)
        
        return weighted_average([...])
```

#### 3. **Decision Engine V2**
```python
def decide(signal: Signal, market: MarketState) -> Decision:
    score = credibility_scorer.score(signal)
    
    if score > 0.8 and market.aligned:
        return EXECUTE
    elif score > 0.6:
        return WAIT_AND_MONITOR
    elif score > 0.4:
        return PARTIAL_SIZE
    else:
        return REJECT
```

**Duration:** 4-6 هفته  
**Deliverable:** Intelligent signal analysis

---

## 🎯 Milestones

### Milestone 1: Database Migration ✅ (Week 2)
- [x] Schema designed
- [x] Wrapper implemented
- [ ] Data migrated
- [ ] Production ready

### Milestone 2: Core Refactored (Week 8)
- [ ] All 31 modules extracted
- [ ] Tests passing
- [ ] Legacy code deprecated
- [ ] Documentation complete

### Milestone 3: Services Live (Week 12)
- [ ] 4 services deployed
- [ ] APIs documented
- [ ] Monitoring active
- [ ] V1.5 production-ready

### Milestone 4: Bridge V2 (Week 14)
- [ ] WebSocket connection
- [ ] Failover working
- [ ] Real-time proven

### Milestone 5: AI Analyzer (Week 18)
- [ ] NLP parser
- [ ] Credibility scoring
- [ ] Decision engine V2
- [ ] Full system integration

---

## 📊 Success Metrics

### Technical:
- ✅ Code coverage > 80%
- ✅ All tests green
- ✅ No circular dependencies
- ✅ API response time < 100ms
- ✅ Database queries < 50ms

### Business:
- ✅ Uptime > 99.9%
- ✅ Signal processing < 1s
- ✅ Trade execution < 2s
- ✅ Zero data loss

### Quality:
- ✅ Maintainable code
- ✅ Clear architecture
- ✅ Good documentation
- ✅ Easy to extend

---

## ⚠️ Risks & Mitigation

### Risk 1: Breaking production
**Mitigation:**
- Dual-write mode (old + new)
- Feature flags
- Gradual rollout
- Easy rollback

### Risk 2: Performance regression
**Mitigation:**
- Benchmark before/after
- Load testing
- Profiling

### Risk 3: Data inconsistency
**Mitigation:**
- Transaction support
- Data validation
- Integrity checks
- Regular audits

---

## 🚫 چیزهایی که نمی‌کنیم

❌ **Complete rewrite** - خیلی risky  
❌ **Clean Architecture سنگین** - Over-engineering  
❌ **V2 brain/ را ادامه بدیم** - پایه‌های بد  
❌ **همه چیز یکجا** - باید incremental باشد  
❌ **بدون test** - Quality اول  

---

## ✅ چیزهایی که می‌کنیم

✅ **Incremental refactoring** - کم کم پیش می‌ریم  
✅ **Test everything** - قبل از هر قدم  
✅ **Keep V1 alive** - تا V1.5 آماده شد  
✅ **Pragmatic approach** - نه perfect، بلکه working  
✅ **Database first** - پایه محکم  
✅ **Documentation** - همه چیز مستند  

---

## 📝 تصمیمات معماری

### ADR-001: SQLite First, PostgreSQL Later
**Context:** نیاز به database مرکزی  
**Decision:** شروع با SQLite، migrate به PostgreSQL بعداً  
**Rationale:** SQLite سریع‌تر برای شروع، zero ops overhead  

### ADR-002: No Microservices (Yet)
**Context:** Service extraction  
**Decision:** Modular monolith با internal APIs  
**Rationale:** Microservices complexity زیاده، بعداً می‌شه جدا کرد  

### ADR-003: Keep Legacy Code
**Context:** Refactoring  
**Decision:** Legacy code را deprecate می‌کنیم نه delete  
**Rationale:** Safety net برای rollback  

### ADR-004: Strangler Fig Pattern
**Context:** Migration strategy  
**Decision:** تدریجی replace کن  
**Rationale:** Low risk، proven pattern  

---

## 🎓 Lessons Learned

### از شکست V2:
1. **Don't rewrite everything at once** - خیلی risky
2. **Finish what you start** - V2 نصفه موند
3. **Keep it simple** - Clean Architecture خیلی پیچیده بود
4. **Pragmatic over perfect** - Perfect = enemy of done

### برای موفقیت V1.5:
1. **One step at a time** - هر قدم کامل بشه
2. **Test everything** - No surprises
3. **Keep it running** - Production اول
4. **Document everything** - برای آینده

---

## 📞 Contact & Support

**Developer:** Seyed Mahdi Esmailian  
**Repository:** github.com/seyedmahdiesmailian/hermes-trading  
**Branch:** arena/01a0bb32-hermes-trading  

---

**Last Updated:** 2026-10-15  
**Next Review:** Weekly (every Monday)
