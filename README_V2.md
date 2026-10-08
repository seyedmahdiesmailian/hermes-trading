# Hermes Trading V2 — Clean Architecture

**🧠 Intelligent Trading System** با معماری تمیز و مهندسی‌شده

---

## 🎯 معماری

```
┌─────────────────────────────────────────────────────────────┐
│                    HERMES BRAIN V2                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  🧠 Domain Layer (Core Business Logic)                     │
│  ├─ Entities: Market, Trade, Signal, Plan, Account         │
│  ├─ Value Objects: Price, Risk, TimeFrame, Setup           │
│  ├─ Services: Analyzer, DecisionEngine, Risk, Learning     │
│  └─ Repositories: Interfaces (ports)                        │
│                                                             │
│  ⚙️ Application Layer (Use Cases)                          │
│  ├─ AutonomousTradingUseCase                               │
│  ├─ SignalProcessingUseCase                                │
│  └─ PositionManagementUseCase                              │
│                                                             │
│  🔌 Adapters Layer (External Integrations)                 │
│  ├─ MT5Gateway (Windows bridge)                            │
│  ├─ JSONRepository (file storage)                          │
│  └─ TelegramGateway (future)                               │
│                                                             │
│  🏗️ Infrastructure (Cross-cutting)                         │
│  ├─ Config (env loader)                                    │
│  ├─ DIContainer (dependency injection)                     │
│  └─ Logger (future)                                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Setup

```bash
# در branch جدید هستیم
git checkout feature/brain-rewrite-v2

# Dependencies (همان قبلی)
pip install -r requirements.txt
```

### 2. Config

```bash
# .env فایل (همان قبلی کار می‌کند)
HERMES_DRY_RUN=true
HERMES_BRIDGE_URL=http://192.168.10.51:5050
HERMES_BRIDGE_TOKEN=your_token
DATA_DIR=/home/ai/hermes-trading/data
```

### 3. Run

```bash
# Autonomous cycle (manual test)
python3 entry_points/cron_master.py

# Or via cron (production)
# Already configured in crontab
```

---

## 📦 Structure

```
hermes-trading/
├── brain/                      # 🧠 Core (Domain + Application)
│   ├── domain/
│   │   ├── entities/          # Business objects
│   │   ├── value_objects/     # Immutable values
│   │   ├── services/          # Business logic
│   │   └── repositories/      # Interfaces
│   └── application/
│       └── use_cases/         # Application flows
│
├── adapters/                   # 🔌 External integrations
│   └── gateways/
│       ├── mt5/               # MT5 Windows bridge
│       ├── data/              # JSON storage
│       └── telegram/          # (future)
│
├── infrastructure/             # 🏗️ Cross-cutting
│   ├── config.py
│   └── di_container.py
│
├── entry_points/               # 🚪 Entry points
│   ├── cron_master.py         # Main cycle
│   ├── daemon_position.py     # (future)
│   └── daemon_signal.py       # (future)
│
├── tests/                      # 🧪 Tests
├── data/                       # 📁 Runtime data
├── docs/                       # 📚 Documentation
└── legacy/                     # 🗄️ Old V1 code (reference)
```

---

## 🎯 Use Cases

### 1. Autonomous Trading

```python
from infrastructure.di_container import DIContainer
from brain.application.use_cases import (
    AutonomousTradingUseCase,
    AutonomousTradingRequest
)

# Setup
container = DIContainer()
container.load_config('.env')
container.wire()

# Execute
use_case = container.get(AutonomousTradingUseCase)
request = AutonomousTradingRequest(symbol="XAUUSD", timeframe="M15")
response = use_case.execute(request)

print(response.action_taken)  # "trade_ready" / "waiting" / "no_action"
```

### 2. Signal Processing

```python
from brain.domain.entities.signal import Signal, SignalSource
from brain.application.use_cases import (
    SignalProcessingUseCase,
    ProcessSignalRequest
)

# Create signal
signal = Signal(
    symbol="XAUUSD",
    direction="buy",
    entry_price=2650.0,
    stop_loss=2630.0,
    take_profit=2690.0,
    source=SignalSource.TELEGRAM
)

# Process
use_case = container.get(SignalProcessingUseCase)
request = ProcessSignalRequest(signal=signal)
response = use_case.execute(request)

print(response.accepted)  # True/False
print(response.reasoning)  # Detailed reasoning
```

### 3. Position Management

```python
from brain.application.use_cases import (
    PositionManagementUseCase,
    ManagePositionRequest
)

# Manage positions
use_case = container.get(PositionManagementUseCase)
request = ManagePositionRequest(symbol="XAUUSD")
response = use_case.execute(request)

print(f"Managed {response.positions_managed} positions")
print(response.actions_taken)  # List of actions
```

---

## ✨ Key Features

### Clean Architecture ✅
- Domain مستقل از همه چیز
- Testable
- Extensible
- SOLID principles

### Multi-Factor Decision Making ✅
- Analysis quality (30%)
- Risk rules (30%)
- Market conditions (20%)
- Learned patterns (10%)
- Timing (10%)

### Risk Management ✅
- 2% risk per trade
- RR ≥ 2.0
- Daily loss limit (5%)
- Max positions (1)
- Adaptive risk

### Learning System ✅
- Pattern extraction
- Performance tracking
- Continuous learning
- Win rate calculation

---

## 🔄 Migration از V1

**V1 (engines/) همچنان کار می‌کند.**

V2 موازی است و هنوز در حال توسعه.

برای تست V2:
```bash
git checkout feature/brain-rewrite-v2
python3 entry_points/cron_master.py
```

برای برگشت به V1:
```bash
git checkout main
```

---

## 📊 Progress

- ✅ Domain Layer (100%)
- ✅ Application Layer (100%)
- ✅ Adapters Layer (80%)
- ✅ Infrastructure (80%)
- ⏳ Integration Testing (0%)
- ⏳ Deployment (0%)

**Overall: ~75% complete**

---

## 🚧 TODO

- [ ] Analysis strategies (SMC, Classic)
- [ ] Telegram gateway
- [ ] Complete dict↔entity conversions in JSONRepository
- [ ] Integration tests
- [ ] Migration script V1→V2
- [ ] Performance testing
- [ ] Documentation complete

---

**Built with ❤️ using Clean Architecture**
