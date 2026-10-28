"""Repository Interfaces — Data access abstractions.

These are ports (interfaces) that define how the domain accesses data.
Implementations (adapters) will be in the adapters layer.
"""

from .market_data_repo import IMarketDataRepository
from .trade_repo import ITradeRepository
from .state_repo import IStateRepository
from .signal_repo import ISignalRepository

__all__ = [
    'IMarketDataRepository',
    'ITradeRepository',
    'IStateRepository',
    'ISignalRepository',
]
