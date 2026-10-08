# Hermes Trading V2 — معماری مهندسی شده (Clean Architecture)

**نسخه:** 2.0  
**تاریخ:** 2026-10-08  
**وضعیت:** طراحی تفصیلی  
**مدل:** Rewrite با Clean Architecture  

---

## 🎯 اصول طراحی

### 1. Clean Architecture Principles

```
┌─────────────────────────────────────────────────────────┐
│                    External Layer                       │
│  (UI, Telegram, MT5 Bridge, File System, Database)     │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│              Interface Adapters Layer                   │
│     (Controllers, Presenters, Gateways)                 │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│              Use Cases Layer                            │
│    (Application Business Rules)                         │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                 Domain Layer                            │
│     (Enterprise Business Rules - Core Logic)            │
└─────────────────────────────────────────────────────────┘
```

**قوانین:**
- وابستگی‌ها فقط به **داخل** (Domain هیچ وابستگی به خارج ندارد)
- Domain مستقل از framework/database/UI
- Use Cases منطق اپلیکیشن را کنترل می‌کنند
- Interface Adapters بین لایه‌ها ترجمه می‌کنند

### 2. SOLID Principles

- **S**ingle Responsibility
- **O**pen/Closed
- **L**iskov Substitution
- **I**nterface Segregation
- **D**ependency Inversion

### 3. Design Patterns استفاده‌شده

- **Strategy Pattern** — برای الگوریتم‌های مختلف تحلیل
- **Observer Pattern** — برای event-driven architecture
- **Repository Pattern** — برای data access
- **Factory Pattern** — برای ساخت objects
- **Command Pattern** — برای order execution
- **State Pattern** — برای position lifecycle

---

## 🏗️ معماری کلی V2

```
┌──────────────────────────────────────────────────────────────────┐
│                     HERMES BRAIN V2                              │
│                   (Linux Server — مغز)                           │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              🧠 INTELLIGENCE CORE                          │ │
│  │                  (Domain Layer)                            │ │
│  ├────────────────────────────────────────────────────────────┤ │
│  │                                                            │ │
│  │  ┌─────────────┐   ┌──────────────┐   ┌───────────────┐  │ │
│  │  │   Market    │   │   Decision   │   │   Learning    │  │ │
│  │  │  Analyzer   │──▶│    Engine    │◀──│     Loop      │  │ │
│  │  │             │   │              │   │               │  │ │
│  │  └─────────────┘   └──────────────┘   └───────────────┘  │ │
│  │         │                  │                   │          │ │
│  │         └──────────────────┼───────────────────┘          │ │
│  │                            │                              │ │
│  │                   ┌────────▼────────┐                     │ │
│  │                   │  Knowledge Base │                     │ │
│  │                   │  (Domain Model) │                     │ │
│  │                   └─────────────────┘                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            │                                    │
│  ┌────────────────────────▼──────────────────────────────────┐ │
│  │              ⚙️ APPLICATION LAYER                         │ │
│  │                 (Use Cases)                                │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │                                                            │ │
│  │  ┌────────────┐  ┌────────────┐  ┌─────────────────┐    │ │
│  │  │ Autonomous │  │  Signal    │  │   Position      │    │ │
│  │  │  Trading   │  │ Processing │  │  Management     │    │ │
│  │  │  UseCase   │  │  UseCase   │  │   UseCase       │    │ │
│  │  └────────────┘  └────────────┘  └─────────────────┘    │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            │                                    │
│  ┌────────────────────────▼──────────────────────────────────┐ │
│  │           🔌 INTERFACE ADAPTERS                            │ │
│  │        (Controllers, Gateways, Presenters)                 │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │                                                            │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐  │ │
│  │  │ Telegram │  │   MT5    │  │   Data   │  │  Cron   │  │ │
│  │  │ Gateway  │  │ Gateway  │  │ Gateway  │  │ Gateway │  │ │
│  │  └──────────┘  └──────────┘  └──────────┘  └─────────┘  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            │                                    │
└────────────────────────────┼────────────────────────────────────┘
                             │
              ┌──────────────┴───────────────┐
              │                              │
              ▼                              ▼
    ┌─────────────────┐          ┌──────────────────┐
    │   Telegram Bot  │          │  MT5 Bridge      │
    │   (External)    │          │  (Windows)       │
    └─────────────────┘          └──────────────────┘
```

---

## 📂 ساختار Directory جدید

```
hermes-trading/
│
├── brain/                          # 🧠 CORE — Domain + Use Cases
│   │
│   ├── domain/                     # Domain Layer (قلب سیستم)
│   │   ├── __init__.py
│   │   ├── entities/               # Domain Entities
│   │   │   ├── __init__.py
│   │   │   ├── market.py           # Market, Candle, Tick
│   │   │   ├── trade.py            # Trade, Position, Order
│   │   │   ├── signal.py           # Signal entity
│   │   │   ├── plan.py             # TradingPlan entity
│   │   │   └── account.py          # Account, Balance
│   │   │
│   │   ├── value_objects/          # Value Objects (immutable)
│   │   │   ├── __init__.py
│   │   │   ├── price.py            # Price, PriceLevel
│   │   │   ├── timeframe.py        # TimeFrame
│   │   │   ├── risk.py             # RiskParameters
│   │   │   └── setup.py            # SetupGrade, SetupType
│   │   │
│   │   ├── services/               # Domain Services
│   │   │   ├── __init__.py
│   │   │   ├── market_analyzer.py  # 📊 Market Analysis Service
│   │   │   ├── decision_engine.py  # 🎯 Decision Making Service
│   │   │   ├── risk_manager.py     # ⚠️ Risk Management Service
│   │   │   └── learning_engine.py  # 🧠 Learning Service
│   │   │
│   │   └── repositories/           # Repository Interfaces (abstractions)
│   │       ├── __init__.py
│   │       ├── market_data_repo.py
│   │       ├── trade_repo.py
│   │       ├── signal_repo.py
│   │       └── state_repo.py
│   │
│   ├── application/                # Application Layer (Use Cases)
│   │   ├── __init__.py
│   │   ├── use_cases/
│   │   │   ├── __init__.py
│   │   │   ├── autonomous_trading.py   # UC: Scan → Plan → Execute
│   │   │   ├── signal_processing.py    # UC: Telegram Signal → Execute
│   │   │   ├── position_management.py  # UC: Manage Open Positions
│   │   │   └── learning.py             # UC: Learn from closed trades
│   │   │
│   │   ├── dto/                    # Data Transfer Objects
│   │   │   ├── __init__.py
│   │   │   ├── analysis_result.py
│   │   │   ├── trade_proposal.py
│   │   │   └── execution_result.py
│   │   │
│   │   └── ports/                  # Port interfaces
│   │       ├── __init__.py
│   │       ├── market_data_port.py
│   │       ├── execution_port.py
│   │       ├── notification_port.py
│   │       └── storage_port.py
│   │
│   └── __init__.py
│
├── adapters/                       # 🔌 Interface Adapters Layer
│   ├── __init__.py
│   │
│   ├── controllers/                # Controllers (orchestration)
│   │   ├── __init__.py
│   │   ├── cron_controller.py      # Cron entry point
│   │   ├── daemon_controller.py    # Daemon entry point
│   │   └── cli_controller.py       # CLI commands
│   │
│   ├── gateways/                   # External system adapters
│   │   ├── __init__.py
│   │   ├── mt5/
│   │   │   ├── __init__.py
│   │   │   ├── mt5_gateway.py      # MT5 communication
│   │   │   ├── mt5_mapper.py       # MT5 data mapping
│   │   │   └── mt5_client.py       # HTTP client to bridge
│   │   │
│   │   ├── telegram/
│   │   │   ├── __init__.py
│   │   │   ├── telegram_gateway.py # Telegram bot
│   │   │   ├── signal_parser.py    # Parse signal messages
│   │   │   └── notifier.py         # Send notifications
│   │   │
│   │   └── data/
│   │       ├── __init__.py
│   │       ├── json_repository.py  # JSON file storage
│   │       └── state_manager.py    # State persistence
│   │
│   ├── presenters/                 # Output formatting
│   │   ├── __init__.py
│   │   ├── telegram_presenter.py
│   │   └── log_presenter.py
│   │
│   └── __init__.py
│
├── infrastructure/                 # ⚙️ Infrastructure
│   ├── __init__.py
│   ├── config.py                   # Configuration loader
│   ├── logger.py                   # Logging setup
│   ├── di_container.py             # Dependency Injection
│   └── scheduler.py                # Task scheduling
│
├── analysis/                       # 📊 Analysis Engines (ماژول‌های تحلیل)
│   ├── __init__.py
│   ├── technical/
│   │   ├── __init__.py
│   │   ├── smc_analyzer.py         # SMC/ICT analysis
│   │   ├── classic_analyzer.py     # Classic technical
│   │   ├── indicators.py           # Technical indicators
│   │   └── patterns.py             # Chart patterns
│   │
│   ├── fundamental/
│   │   ├── __init__.py
│   │   ├── economic_calendar.py
│   │   ├── news_analyzer.py
│   │   └── sentiment.py
│   │
│   └── market_regime/
│       ├── __init__.py
│       ├── trend_detector.py
│       ├── volatility_analyzer.py
│       └── regime_classifier.py
│
├── entry_points/                   # 🚪 Application Entry Points
│   ├── __init__.py
│   ├── cron_master.py              # Cron job entry (5-min cycle)
│   ├── daemon_position.py          # Position management daemon
│   ├── daemon_signal.py            # Signal listener daemon
│   └── cli.py                      # CLI interface
│
├── tests/                          # 🧪 Tests
│   ├── unit/
│   │   ├── domain/
│   │   ├── application/
│   │   └── adapters/
│   ├── integration/
│   └── e2e/
│
├── data/                           # 📁 Runtime data (state, logs)
├── docs/                           # 📚 Documentation
├── scripts/                        # 🔧 Utility scripts
├── legacy/                         # 🗄️ Old code (reference only)
│
├── .env                            # Environment variables
├── requirements.txt                # Python dependencies
├── setup.py                        # Package setup
└── README.md
```

---

## 🎨 Domain Model (Core Entities)

### 1. Market Domain

```python
# brain/domain/entities/market.py

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass(frozen=True)
class Candle:
    """Immutable candle entity."""
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    
    @property
    def body(self) -> float:
        return abs(self.close - self.open)
    
    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

@dataclass
class MarketState:
    """Current market state snapshot."""
    symbol: str
    timeframe: str
    candles: list[Candle]
    current_price: float
    timestamp: datetime
    
    def latest_candle(self) -> Candle:
        return self.candles[-1]
```

### 2. Trade Domain

```python
# brain/domain/entities/trade.py

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class OrderType(Enum):
    BUY = "buy"
    SELL = "sell"

class OrderStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"

@dataclass
class Order:
    """Trading order."""
    id: str
    symbol: str
    type: OrderType
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    comment: str
    timestamp: datetime
    status: OrderStatus = OrderStatus.PENDING
    
    def risk_reward_ratio(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk > 0 else 0.0

@dataclass
class Position:
    """Open trading position."""
    ticket: int
    order: Order
    open_time: datetime
    open_price: float
    current_price: float
    profit: float
    max_profit: float = 0.0  # MFE (Max Favorable Excursion)
    max_loss: float = 0.0    # MAE (Max Adverse Excursion)
    
    def update_price(self, new_price: float):
        """Update current price and track MFE/MAE."""
        self.current_price = new_price
        self.profit = self._calculate_profit()
        
        if self.profit > self.max_profit:
            self.max_profit = self.profit
        if self.profit < self.max_loss:
            self.max_loss = self.profit
    
    def _calculate_profit(self) -> float:
        if self.order.type == OrderType.BUY:
            return (self.current_price - self.open_price) * self.order.volume
        else:
            return (self.open_price - self.current_price) * self.order.volume
```

### 3. Signal Domain

```python
# brain/domain/entities/signal.py

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class SignalSource(Enum):
    TELEGRAM = "telegram"
    INTERNAL = "internal"

class SignalQuality(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    REJECTED = "rejected"

@dataclass
class Signal:
    """Trading signal entity."""
    id: str
    source: SignalSource
    symbol: str
    direction: str  # "buy" or "sell"
    entry_price: float
    stop_loss: float
    take_profit: float
    timestamp: datetime
    raw_message: str
    quality: SignalQuality = SignalQuality.MEDIUM
    confidence_score: float = 0.5
    
    def risk_reward_ratio(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk > 0 else 0.0
```

### 4. Plan Domain

```python
# brain/domain/entities/plan.py

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class SetupGrade(Enum):
    """Setup quality grade."""
    A = "A"  # Excellent
    B = "B"  # Good
    C = "C"  # Acceptable
    D = "D"  # Poor
    F = "F"  # Failed

class PlanStage(Enum):
    """Trading plan lifecycle stage."""
    ANALYSIS = "analysis"
    WAITING = "waiting"
    READY = "ready"
    EXECUTED = "executed"
    CLOSED = "closed"
    EXPIRED = "expired"

@dataclass
class TradingPlan:
    """Complete trading plan."""
    id: str
    symbol: str
    direction: str
    setup_grade: SetupGrade
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    reasoning: dict  # تحلیل و دلایل
    created_at: datetime
    stage: PlanStage = PlanStage.ANALYSIS
    executed_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    
    def is_executable(self) -> bool:
        """Check if plan is ready for execution."""
        return (
            self.stage == PlanStage.READY and
            self.setup_grade.value <= SetupGrade.B.value
        )
```

---

## 🧠 Domain Services (Business Logic)

### 1. MarketAnalyzer Service

```python
# brain/domain/services/market_analyzer.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

@dataclass
class AnalysisResult:
    """Market analysis output."""
    trend: str  # "bullish", "bearish", "ranging"
    strength: float  # 0.0 to 1.0
    key_levels: dict  # support/resistance
    patterns: list[str]
    quality_score: float
    reasoning: dict

class IAnalysisStrategy(Protocol):
    """Strategy interface for different analysis types."""
    
    def analyze(self, market_state) -> AnalysisResult:
        """Analyze market and return result."""
        ...

class MarketAnalyzer:
    """Market analysis service — orchestrates multiple strategies."""
    
    def __init__(self):
        self._strategies: list[IAnalysisStrategy] = []
    
    def add_strategy(self, strategy: IAnalysisStrategy):
        """Add an analysis strategy (SMC, Classic, ML, etc)."""
        self._strategies.append(strategy)
    
    def analyze(self, market_state) -> AnalysisResult:
        """Run all strategies and merge results."""
        results = [s.analyze(market_state) for s in self._strategies]
        return self._merge_results(results)
    
    def _merge_results(self, results: list[AnalysisResult]) -> AnalysisResult:
        """Merge multiple analysis results with weighted scoring."""
        # Implementation: weighted average, confluence detection, etc.
        ...
```

### 2. DecisionEngine Service

```python
# brain/domain/services/decision_engine.py

from dataclasses import dataclass
from enum import Enum

class Decision(Enum):
    ENTER_TRADE = "enter"
    EXIT_TRADE = "exit"
    MODIFY_TRADE = "modify"
    WAIT = "wait"
    REJECT = "reject"

@dataclass
class DecisionResult:
    """Decision output."""
    decision: Decision
    confidence: float
    reasoning: dict
    action_params: dict  # parameters for the action

class DecisionEngine:
    """Core decision-making engine."""
    
    def __init__(self, risk_manager, learning_engine):
        self.risk_manager = risk_manager
        self.learning_engine = learning_engine
    
    def evaluate_entry(self, 
                      analysis: AnalysisResult,
                      market_state,
                      account_state) -> DecisionResult:
        """Decide whether to enter a trade."""
        
        # Multi-factor evaluation
        factors = {
            'analysis_quality': self._score_analysis(analysis),
            'risk_acceptable': self.risk_manager.check_risk(account_state),
            'market_conditions': self._check_market_conditions(market_state),
            'learned_patterns': self.learning_engine.match_patterns(analysis),
            'timing': self._check_timing(market_state)
        }
        
        # Weighted decision
        decision, confidence = self._make_decision(factors)
        
        return DecisionResult(
            decision=decision,
            confidence=confidence,
            reasoning=factors,
            action_params=self._build_action_params(analysis, market_state)
        )
    
    def evaluate_exit(self, position, market_state) -> DecisionResult:
        """Decide whether to exit/modify a position."""
        ...
    
    def _make_decision(self, factors: dict) -> tuple[Decision, float]:
        """Core decision logic with weighted scoring."""
        # Implementation: weighted sum, thresholds, etc.
        ...
```

### 3. RiskManager Service

```python
# brain/domain/services/risk_manager.py

from dataclasses import dataclass

@dataclass
class RiskParameters:
    max_risk_per_trade_pct: float = 0.02  # 2%
    max_daily_loss_pct: float = 0.05      # 5%
    max_open_positions: int = 1
    min_risk_reward: float = 2.0
    max_daily_trades: int = 5

@dataclass
class AccountState:
    balance: float
    equity: float
    open_positions: int
    daily_pnl: float
    daily_trades: int

class RiskManager:
    """Risk management service."""
    
    def __init__(self, params: RiskParameters):
        self.params = params
    
    def check_risk(self, account: AccountState) -> bool:
        """Check if new trade is allowed under risk rules."""
        
        # Daily loss limit
        if account.daily_pnl < -self.params.max_daily_loss_pct * account.balance:
            return False
        
        # Max positions
        if account.open_positions >= self.params.max_open_positions:
            return False
        
        # Max daily trades
        if account.daily_trades >= self.params.max_daily_trades:
            return False
        
        return True
    
    def calculate_position_size(self,
                               account: AccountState,
                               entry_price: float,
                               stop_loss: float) -> float:
        """Calculate position size based on risk."""
        risk_amount = account.balance * self.params.max_risk_per_trade_pct
        risk_per_lot = abs(entry_price - stop_loss)
        return risk_amount / risk_per_lot if risk_per_lot > 0 else 0.0
```

### 4. LearningEngine Service

```python
# brain/domain/services/learning_engine.py

from dataclasses import dataclass
from typing import List

@dataclass
class TradeOutcome:
    """Closed trade with full context."""
    plan_id: str
    setup_grade: str
    analysis: dict
    entry_price: float
    exit_price: float
    profit: float
    exit_reason: str
    mfe: float  # Max Favorable Excursion
    mae: float  # Max Adverse Excursion

@dataclass
class Pattern:
    """Learned pattern."""
    id: str
    features: dict
    win_rate: float
    avg_profit: float
    sample_size: int

class LearningEngine:
    """Learning from past trades."""
    
    def __init__(self):
        self.patterns: List[Pattern] = []
    
    def learn_from_trade(self, outcome: TradeOutcome):
        """Extract lessons from a closed trade."""
        
        # Extract features
        features = self._extract_features(outcome)
        
        # Find similar pattern or create new
        pattern = self._find_similar_pattern(features)
        if pattern:
            self._update_pattern(pattern, outcome)
        else:
            self._create_pattern(features, outcome)
    
    def match_patterns(self, analysis: AnalysisResult) -> dict:
        """Find matching patterns and return insights."""
        features = self._extract_features_from_analysis(analysis)
        
        matches = [
            p for p in self.patterns
            if self._similarity(p.features, features) > 0.8
        ]
        
        if matches:
            best = max(matches, key=lambda p: p.win_rate)
            return {
                'pattern_found': True,
                'win_rate': best.win_rate,
                'avg_profit': best.avg_profit,
                'confidence': best.sample_size / 10.0  # normalized
            }
        
        return {'pattern_found': False}
    
    def _extract_features(self, outcome: TradeOutcome) -> dict:
        """Extract learnable features from trade."""
        return {
            'grade': outcome.setup_grade,
            'trend': outcome.analysis.get('trend'),
            'strength': outcome.analysis.get('strength'),
            'rr': abs(outcome.exit_price - outcome.entry_price) / 
                  abs(outcome.analysis.get('stop_loss', 0) - outcome.entry_price)
        }
```

---

## ⚙️ Application Layer (Use Cases)

### Use Case 1: Autonomous Trading

```python
# brain/application/use_cases/autonomous_trading.py

from dataclasses import dataclass
from brain.domain.services.market_analyzer import MarketAnalyzer
from brain.domain.services.decision_engine import DecisionEngine, Decision
from brain.application.ports.market_data_port import IMarketDataPort
from brain.application.ports.execution_port import IExecutionPort

@dataclass
class AutonomousTradingRequest:
    symbol: str
    timeframe: str

@dataclass
class AutonomousTradingResponse:
    success: bool
    action_taken: str
    details: dict

class AutonomousTradingUseCase:
    """Use Case: Autonomous market scan → analyze → decide → execute."""
    
    def __init__(self,
                 market_analyzer: MarketAnalyzer,
                 decision_engine: DecisionEngine,
                 market_data: IMarketDataPort,
                 execution: IExecutionPort):
        self.market_analyzer = market_analyzer
        self.decision_engine = decision_engine
        self.market_data = market_data
        self.execution = execution
    
    def execute(self, request: AutonomousTradingRequest) -> AutonomousTradingResponse:
        """Execute the autonomous trading cycle."""
        
        # 1. Fetch market data
        market_state = self.market_data.get_current_state(
            request.symbol, 
            request.timeframe
        )
        
        # 2. Analyze market
        analysis = self.market_analyzer.analyze(market_state)
        
        # 3. Get account state
        account_state = self.execution.get_account_state()
        
        # 4. Make decision
        decision_result = self.decision_engine.evaluate_entry(
            analysis=analysis,
            market_state=market_state,
            account_state=account_state
        )
        
        # 5. Act on decision
        if decision_result.decision == Decision.ENTER_TRADE:
            execution_result = self.execution.place_order(
                decision_result.action_params
            )
            
            return AutonomousTradingResponse(
                success=True,
                action_taken="trade_opened",
                details={
                    'analysis': analysis,
                    'decision': decision_result,
                    'execution': execution_result
                }
            )
        
        return AutonomousTradingResponse(
            success=True,
            action_taken="no_action",
            details={'decision': decision_result}
        )
```

### Use Case 2: Signal Processing

```python
# brain/application/use_cases/signal_processing.py

from dataclasses import dataclass
from brain.domain.entities.signal import Signal
from brain.domain.services.decision_engine import DecisionEngine

@dataclass
class ProcessSignalRequest:
    signal: Signal

@dataclass
class ProcessSignalResponse:
    accepted: bool
    reasoning: dict
    action_taken: str

class SignalProcessingUseCase:
    """Use Case: Process Telegram signal → validate → cross-check → execute."""
    
    def __init__(self,
                 decision_engine: DecisionEngine,
                 market_analyzer,
                 execution_port):
        self.decision_engine = decision_engine
        self.market_analyzer = market_analyzer
        self.execution = execution_port
    
    def execute(self, request: ProcessSignalRequest) -> ProcessSignalResponse:
        """Process incoming signal."""
        
        signal = request.signal
        
        # 1. Fetch current market state for validation
        market_state = self._get_market_state(signal.symbol)
        
        # 2. Analyze market independently
        our_analysis = self.market_analyzer.analyze(market_state)
        
        # 3. Cross-validate signal with our analysis
        validation = self._cross_validate(signal, our_analysis, market_state)
        
        if not validation['accepted']:
            return ProcessSignalResponse(
                accepted=False,
                reasoning=validation,
                action_taken="rejected"
            )
        
        # 4. Get account state
        account_state = self.execution.get_account_state()
        
        # 5. Make final decision
        decision = self.decision_engine.evaluate_signal_entry(
            signal=signal,
            our_analysis=our_analysis,
            market_state=market_state,
            account_state=account_state
        )
        
        # 6. Execute if approved
        if decision.decision == Decision.ENTER_TRADE:
            execution_result = self.execution.place_order(
                decision.action_params
            )
            
            return ProcessSignalResponse(
                accepted=True,
                reasoning=decision.reasoning,
                action_taken="executed"
            )
        
        return ProcessSignalResponse(
            accepted=False,
            reasoning=decision.reasoning,
            action_taken="rejected_by_decision_engine"
        )
    
    def _cross_validate(self, signal, our_analysis, market_state) -> dict:
        """Cross-check signal against our own analysis."""
        
        # Check confluence
        direction_match = signal.direction == our_analysis.trend
        rr_acceptable = signal.risk_reward_ratio() >= 2.0
        timing_good = self._check_market_timing(market_state)
        quality_score = our_analysis.quality_score
        
        accepted = (
            direction_match and
            rr_acceptable and
            timing_good and
            quality_score > 0.6
        )
        
        return {
            'accepted': accepted,
            'direction_match': direction_match,
            'rr_acceptable': rr_acceptable,
            'timing_good': timing_good,
            'quality_score': quality_score
        }
```

---

## 🔌 Interface Adapters

### MT5 Gateway

```python
# adapters/gateways/mt5/mt5_gateway.py

from brain.application.ports.execution_port import IExecutionPort
from brain.domain.entities.trade import Order, Position
import requests

class MT5Gateway(IExecutionPort):
    """Adapter for MT5 bridge communication."""
    
    def __init__(self, bridge_url: str, token: str):
        self.bridge_url = bridge_url
        self.token = token
    
    def get_account_state(self):
        """Fetch account info from MT5."""
        response = requests.get(
            f"{self.bridge_url}/api/account",
            headers={'Authorization': f'Bearer {self.token}'},
            timeout=10
        )
        
        if response.ok:
            data = response.json()
            return self._map_account_state(data)
        
        raise Exception(f"MT5 connection failed: {response.text}")
    
    def place_order(self, params: dict) -> dict:
        """Place order on MT5."""
        payload = self._build_order_payload(params)
        
        response = requests.post(
            f"{self.bridge_url}/api/order",
            headers={'Authorization': f'Bearer {self.token}'},
            json=payload,
            timeout=30
        )
        
        if response.ok:
            return response.json()
        
        raise Exception(f"Order failed: {response.text}")
    
    def get_positions(self, symbol: str = "XAUUSD") -> list[Position]:
        """Get open positions."""
        response = requests.get(
            f"{self.bridge_url}/api/positions",
            headers={'Authorization': f'Bearer {self.token}'},
            params={'symbol': symbol},
            timeout=10
        )
        
        if response.ok:
            data = response.json()
            return [self._map_position(p) for p in data['data']]
        
        return []
    
    def _map_account_state(self, data: dict):
        """Map MT5 response to domain AccountState."""
        from brain.domain.services.risk_manager import AccountState
        return AccountState(
            balance=data['balance'],
            equity=data['equity'],
            open_positions=0,  # count separately
            daily_pnl=0.0,     # track separately
            daily_trades=0     # track separately
        )
```

### Telegram Gateway

```python
# adapters/gateways/telegram/telegram_gateway.py

from brain.application.ports.notification_port import INotificationPort
import requests

class TelegramGateway(INotificationPort):
    """Adapter for Telegram Bot API."""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    def send_notification(self, message: str, **kwargs):
        """Send message to Telegram."""
        
        payload = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': 'Markdown',
            **kwargs
        }
        
        response = requests.post(
            f"{self.base_url}/sendMessage",
            json=payload,
            timeout=10
        )
        
        return response.ok
    
    def send_trade_alert(self, trade_details: dict):
        """Send formatted trade alert."""
        message = self._format_trade_message(trade_details)
        return self.send_notification(message)
```

---

## 🚪 Entry Points

### Cron Entry Point

```python
# entry_points/cron_master.py

"""Cron job entry point — 5-minute autonomous trading cycle."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.di_container import DIContainer
from adapters.controllers.cron_controller import CronController

def main():
    # Initialize dependency injection container
    container = DIContainer()
    container.load_config()
    container.wire_dependencies()
    
    # Get controller
    controller = container.get(CronController)
    
    # Execute cycle
    try:
        result = controller.execute_cycle()
        print(f"Cycle completed: {result}")
        sys.exit(0)
    except Exception as e:
        print(f"Cycle failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
```

### Controller

```python
# adapters/controllers/cron_controller.py

from brain.application.use_cases.autonomous_trading import (
    AutonomousTradingUseCase,
    AutonomousTradingRequest
)
from brain.application.ports.notification_port import INotificationPort

class CronController:
    """Controller for cron job execution."""
    
    def __init__(self,
                 autonomous_trading_uc: AutonomousTradingUseCase,
                 notifier: INotificationPort):
        self.autonomous_trading = autonomous_trading_uc
        self.notifier = notifier
    
    def execute_cycle(self) -> dict:
        """Execute one complete trading cycle."""
        
        request = AutonomousTradingRequest(
            symbol="XAUUSD",
            timeframe="M15"
        )
        
        response = self.autonomous_trading.execute(request)
        
        # Send notification if action was taken
        if response.action_taken != "no_action":
            self.notifier.send_notification(
                self._format_response(response)
            )
        
        return {
            'success': response.success,
            'action': response.action_taken
        }
    
    def _format_response(self, response) -> str:
        """Format response for notification."""
        # Implementation
        ...
```

---

## 🧪 Testing Strategy

### Test Structure

```
tests/
├── unit/
│   ├── domain/
│   │   ├── test_entities.py
│   │   ├── test_market_analyzer.py
│   │   ├── test_decision_engine.py
│   │   ├── test_risk_manager.py
│   │   └── test_learning_engine.py
│   ├── application/
│   │   ├── test_autonomous_trading_uc.py
│   │   └── test_signal_processing_uc.py
│   └── adapters/
│       ├── test_mt5_gateway.py
│       └── test_telegram_gateway.py
│
├── integration/
│   ├── test_end_to_end_cycle.py
│   └── test_mt5_connection.py
│
└── e2e/
    └── test_full_trading_cycle.py
```

### Example Unit Test

```python
# tests/unit/domain/test_risk_manager.py

import pytest
from brain.domain.services.risk_manager import RiskManager, RiskParameters, AccountState

def test_risk_manager_blocks_on_daily_loss():
    """Risk manager should block new trades after daily loss limit."""
    
    # Arrange
    params = RiskParameters(max_daily_loss_pct=0.05)
    risk_manager = RiskManager(params)
    
    account = AccountState(
        balance=10000,
        equity=9400,
        open_positions=0,
        daily_pnl=-600,  # 6% loss (over limit)
        daily_trades=2
    )
    
    # Act
    allowed = risk_manager.check_risk(account)
    
    # Assert
    assert not allowed, "Should block trade after daily loss limit"

def test_position_size_calculation():
    """Position size should be calculated correctly."""
    
    # Arrange
    params = RiskParameters(max_risk_per_trade_pct=0.02)
    risk_manager = RiskManager(params)
    
    account = AccountState(
        balance=10000,
        equity=10000,
        open_positions=0,
        daily_pnl=0,
        daily_trades=0
    )
    
    # Act
    position_size = risk_manager.calculate_position_size(
        account=account,
        entry_price=2600.0,
        stop_loss=2580.0  # 20 point risk
    )
    
    # Assert
    # Risk: 10000 * 0.02 = 200 USD
    # Risk per lot: 20 points
    # Position size: 200 / 20 = 10 lots
    assert position_size == pytest.approx(10.0)
```

---

## 📦 Dependency Injection

```python
# infrastructure/di_container.py

from typing import Dict, Any, Type
import yaml

class DIContainer:
    """Simple dependency injection container."""
    
    def __init__(self):
        self._services: Dict[Type, Any] = {}
        self._config: dict = {}
    
    def load_config(self, config_path: str = ".env"):
        """Load configuration."""
        from infrastructure.config import load_config
        self._config = load_config(config_path)
    
    def wire_dependencies(self):
        """Wire all dependencies."""
        
        # External adapters (Infrastructure)
        from adapters.gateways.mt5.mt5_gateway import MT5Gateway
        from adapters.gateways.telegram.telegram_gateway import TelegramGateway
        from adapters.gateways.data.json_repository import JSONRepository
        
        mt5_gateway = MT5Gateway(
            bridge_url=self._config['BRIDGE_URL'],
            token=self._config['BRIDGE_TOKEN']
        )
        
        telegram_gateway = TelegramGateway(
            bot_token=self._config['TELEGRAM_BOT_TOKEN'],
            chat_id=self._config['TELEGRAM_CHAT_ID']
        )
        
        data_repo = JSONRepository(data_dir=self._config['DATA_DIR'])
        
        # Domain services
        from brain.domain.services.market_analyzer import MarketAnalyzer
        from brain.domain.services.decision_engine import DecisionEngine
        from brain.domain.services.risk_manager import RiskManager, RiskParameters
        from brain.domain.services.learning_engine import LearningEngine
        
        risk_params = RiskParameters(
            max_risk_per_trade_pct=0.02,
            max_daily_loss_pct=0.05,
            max_open_positions=1,
            min_risk_reward=2.0,
            max_daily_trades=5
        )
        
        risk_manager = RiskManager(risk_params)
        learning_engine = LearningEngine()
        
        market_analyzer = MarketAnalyzer()
        # Add strategies
        from analysis.technical.smc_analyzer import SMCAnalyzer
        from analysis.technical.classic_analyzer import ClassicAnalyzer
        market_analyzer.add_strategy(SMCAnalyzer())
        market_analyzer.add_strategy(ClassicAnalyzer())
        
        decision_engine = DecisionEngine(
            risk_manager=risk_manager,
            learning_engine=learning_engine
        )
        
        # Use cases
        from brain.application.use_cases.autonomous_trading import AutonomousTradingUseCase
        from brain.application.use_cases.signal_processing import SignalProcessingUseCase
        
        autonomous_trading_uc = AutonomousTradingUseCase(
            market_analyzer=market_analyzer,
            decision_engine=decision_engine,
            market_data=mt5_gateway,
            execution=mt5_gateway
        )
        
        signal_processing_uc = SignalProcessingUseCase(
            decision_engine=decision_engine,
            market_analyzer=market_analyzer,
            execution_port=mt5_gateway
        )
        
        # Controllers
        from adapters.controllers.cron_controller import CronController
        
        cron_controller = CronController(
            autonomous_trading_uc=autonomous_trading_uc,
            notifier=telegram_gateway
        )
        
        # Register services
        self._services[MT5Gateway] = mt5_gateway
        self._services[TelegramGateway] = telegram_gateway
        self._services[MarketAnalyzer] = market_analyzer
        self._services[DecisionEngine] = decision_engine
        self._services[RiskManager] = risk_manager
        self._services[LearningEngine] = learning_engine
        self._services[AutonomousTradingUseCase] = autonomous_trading_uc
        self._services[SignalProcessingUseCase] = signal_processing_uc
        self._services[CronController] = cron_controller
    
    def get(self, service_type: Type):
        """Get a service instance."""
        return self._services.get(service_type)
```

---

## 🔄 Migration Plan (از V1 به V2)

### فاز 1: Skeleton (هفته 1)

**اقدامات:**
1. ✅ ساخت directory structure جدید
2. ✅ ایجاد domain entities
3. ✅ پیاده‌سازی interfaces (ports)
4. ✅ ساخت DI container اولیه
5. ✅ نوشتن unit tests برای entities

**Deliverable:**
- ساختار کامل بدون logic
- تست‌های اولیه pass می‌شوند

### فاز 2: Domain Layer (هفته 1-2)

**اقدامات:**
1. ✅ پیاده‌سازی MarketAnalyzer
2. ✅ Migration SMC/Classic analysis به strategies
3. ✅ پیاده‌سازی DecisionEngine
4. ✅ پیاده‌سازی RiskManager
5. ✅ پیاده‌سازی LearningEngine (basic)
6. ✅ Unit tests برای همه services

**Deliverable:**
- Domain layer کامل و tested

### فاز 3: Use Cases (هفته 2)

**اقدامات:**
1. ✅ پیاده‌سازی AutonomousTradingUseCase
2. ✅ پیاده‌سازی SignalProcessingUseCase
3. ✅ پیاده‌سازی PositionManagementUseCase
4. ✅ Integration tests

**Deliverable:**
- Use cases کامل و tested

### فاز 4: Adapters (هفته 2-3)

**اقدامات:**
1. ✅ پیاده‌سازی MT5Gateway
2. ✅ پیاده‌سازی TelegramGateway
3. ✅ پیاده‌سازی DataRepository
4. ✅ Controllers
5. ✅ Integration tests با MT5 واقعی

**Deliverable:**
- Adapters کامل و tested

### فاز 5: Entry Points و Integration (هفته 3)

**اقدامات:**
1. ✅ ساخت entry points
2. ✅ Wire کردن DI container کامل
3. ✅ End-to-end testing
4. ✅ Backtest با داده واقعی
5. ✅ Performance testing

**Deliverable:**
- سیستم کامل و قابل اجرا

### فاز 6: Cutover و Deployment (هفته 3)

**اقدامات:**
1. ✅ Final testing روی demo account
2. ✅ Migration script برای state
3. ✅ Documentation
4. ✅ Cutover به production
5. ✅ Monitoring اولیه
6. ✅ Rollback plan آماده

**Deliverable:**
- سیستم جدید live
- سیستم قدیم archived

---

## 📊 مقایسه V1 vs V2

| معیار | V1 (فعلی) | V2 (جدید) |
|-------|-----------|----------|
| **خطوط کد** | 11,443 | ~5,000 (تخمین) |
| **ماژول‌ها** | 30+ فایل پراکنده | ساختار لایه‌ای واضح |
| **تست‌پذیری** | متوسط | بسیار بالا |
| **وابستگی‌ها** | پیچیده و پراکنده | واضح و مدیریت‌شده |
| **مسئولیت‌ها** | مخلوط | تفکیک شده (SOLID) |
| **یادگیری** | نیمه‌تمام | کامل و فعال |
| **هوشمندی** | Rule-based | Multi-factor + ML-ready |
| **نگهداری** | سخت | آسان |
| **توسعه** | محدود | باز برای توسعه |

---

## 🎯 مزایای معماری V2

### 1. Clean Architecture
✅ **مستقل از Framework** — domain هیچ وابستگی به Flask/Django ندارد  
✅ **Testable** — هر لایه جداگانه قابل تست  
✅ **مستقل از UI** — می‌توان Telegram را با Web جایگزین کرد  
✅ **مستقل از Database** — می‌توان JSON را با PostgreSQL جایگزین کرد  
✅ **مستقل از External Services** — MT5 را می‌توان با IB جایگزین کرد  

### 2. Domain-Driven Design
✅ **Business Logic واضح** — همه منطق در domain است  
✅ **Ubiquitous Language** — entities = واقعیت تجاری  
✅ **Rich Domain Model** — entities رفتار دارند نه فقط data  

### 3. SOLID Principles
✅ **Single Responsibility** — هر class یک مسئولیت  
✅ **Open/Closed** — باز برای توسعه، بسته برای تغییر  
✅ **Dependency Inversion** — وابستگی به abstractions  

### 4. Extensibility
✅ **Strategy Pattern** — اضافه کردن analyzer جدید آسان  
✅ **Plugin Architecture** — اضافه کردن feature بدون تغییر core  
✅ **ML-Ready** — آماده برای یادگیری ماشین  

---

## 📝 نتیجه‌گیری

معماری V2 یک **foundation محکم** برای ساخت "مغز هوشمند تریدینگ" است:

✅ **ساده** — کد واضح و قابل فهم  
✅ **مهندسی شده** — اصول معماری رعایت شده  
✅ **Testable** — قابل تست در همه سطوح  
✅ **Extensible** — آماده برای توسعه و هوش  
✅ **Maintainable** — نگهداری آسان  

**آماده برای شروع implementation! 🚀**

---

**تهیه‌کننده:** Hermes Agent  
**تاریخ:** 2026-10-08  
**نسخه:** 2.0 Design Specification
