"""Dependency Injection Container.

Wires all dependencies together.
"""

from typing import Dict, Type, Any, TypeVar
from pathlib import Path

from infrastructure.config import Config

# Domain
from brain.domain.value_objects.risk import RiskParameters
from brain.domain.services.market_analyzer import MarketAnalyzer
from brain.domain.services.decision_engine import DecisionEngine
from brain.domain.services.risk_manager import RiskManager
from brain.domain.services.learning_engine import LearningEngine

# Application
from brain.application.use_cases.autonomous_trading import AutonomousTradingUseCase
from brain.application.use_cases.signal_processing import SignalProcessingUseCase
from brain.application.use_cases.position_management import PositionManagementUseCase

# Adapters
from adapters.gateways.mt5.mt5_gateway import MT5Gateway
from adapters.gateways.data.json_repository import JSONRepository

T = TypeVar('T')


class DIContainer:
    """Dependency Injection Container.
    
    Manages object creation and wiring.
    
    Usage:
        container = DIContainer()
        container.load_config('/path/to/.env')
        container.wire()
        
        # Get services
        autonomous_uc = container.get(AutonomousTradingUseCase)
        autonomous_uc.execute(...)
    """
    
    def __init__(self):
        self._services: Dict[Type, Any] = {}
        self._config: Config | None = None
    
    def load_config(self, env_file: str | Path | None = None):
        """Load configuration.
        
        Args:
            env_file: Path to .env file
        """
        self._config = Config(env_file)
        self._services[Config] = self._config
    
    def wire(self):
        """Wire all dependencies."""
        if not self._config:
            raise RuntimeError("Config not loaded. Call load_config() first.")
        
        # Infrastructure
        data_dir = self._config.get('DATA_DIR') or '/home/ai/hermes-trading/data'
        
        # Adapters (Gateways)
        mt5_gateway = MT5Gateway(
            bridge_url=self._config.require('HERMES_BRIDGE_URL'),
            token=self._config.require('HERMES_BRIDGE_TOKEN')
        )
        
        json_repo = JSONRepository(data_dir=data_dir)
        
        # Register adapters
        self._services[MT5Gateway] = mt5_gateway
        self._services[JSONRepository] = json_repo
        
        # Domain Services
        risk_params = RiskParameters(
            max_risk_per_trade_pct=self._config.get_float('MAX_RISK_PER_TRADE', 0.02),
            max_daily_loss_pct=self._config.get_float('MAX_DAILY_LOSS', 0.05),
            max_open_positions=self._config.get_int('MAX_OPEN_POSITIONS', 1),
            min_risk_reward=self._config.get_float('MIN_RISK_REWARD', 2.0),
            max_daily_trades=self._config.get_int('MAX_DAILY_TRADES', 5)
        )
        
        risk_manager = RiskManager(risk_params)
        learning_engine = LearningEngine()
        
        market_analyzer = MarketAnalyzer()
        # Note: Strategies would be added here
        # market_analyzer.add_strategy(SMCStrategy())
        # market_analyzer.add_strategy(ClassicStrategy())
        
        decision_engine = DecisionEngine(
            risk_manager=risk_manager,
            learning_engine=learning_engine
        )
        
        # Register domain services
        self._services[RiskParameters] = risk_params
        self._services[RiskManager] = risk_manager
        self._services[LearningEngine] = learning_engine
        self._services[MarketAnalyzer] = market_analyzer
        self._services[DecisionEngine] = decision_engine
        
        # Use Cases
        autonomous_trading_uc = AutonomousTradingUseCase(
            market_analyzer=market_analyzer,
            decision_engine=decision_engine,
            market_data_repo=mt5_gateway,
            trade_repo=json_repo,
            state_repo=json_repo
        )
        
        signal_processing_uc = SignalProcessingUseCase(
            market_analyzer=market_analyzer,
            decision_engine=decision_engine,
            market_data_repo=mt5_gateway,
            signal_repo=json_repo,
            state_repo=json_repo
        )
        
        position_management_uc = PositionManagementUseCase(
            decision_engine=decision_engine,
            market_data_repo=mt5_gateway,
            trade_repo=json_repo
        )
        
        # Register use cases
        self._services[AutonomousTradingUseCase] = autonomous_trading_uc
        self._services[SignalProcessingUseCase] = signal_processing_uc
        self._services[PositionManagementUseCase] = position_management_uc
    
    def get(self, service_type: Type[T]) -> T:
        """Get a service instance.
        
        Args:
            service_type: Service class type
            
        Returns:
            Service instance
            
        Raises:
            KeyError: If service not registered
        """
        if service_type not in self._services:
            raise KeyError(f"Service not registered: {service_type.__name__}")
        
        return self._services[service_type]
    
    def __repr__(self) -> str:
        return f"DIContainer({len(self._services)} services wired)"
