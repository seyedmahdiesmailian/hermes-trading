"""Trade Repository Interface.

Defines how the domain stores and retrieves trade data.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime

from brain.domain.entities.trade import Order, Position
from brain.domain.entities.plan import TradingPlan


class ITradeRepository(ABC):
    """Trade repository interface.
    
    Implementations can store in:
    - JSON files
    - SQLite
    - PostgreSQL
    - MongoDB
    """
    
    @abstractmethod
    def save_plan(self, plan: TradingPlan) -> None:
        """Save a trading plan.
        
        Args:
            plan: Trading plan to save
        """
        ...
    
    @abstractmethod
    def get_plan(self, plan_id: str) -> Optional[TradingPlan]:
        """Get a trading plan by ID.
        
        Args:
            plan_id: Plan ID
            
        Returns:
            TradingPlan if found, None otherwise
        """
        ...
    
    @abstractmethod
    def get_active_plan(self) -> Optional[TradingPlan]:
        """Get the currently active plan.
        
        Returns:
            Active TradingPlan if exists, None otherwise
        """
        ...
    
    @abstractmethod
    def get_plan_history(
        self,
        start: datetime,
        end: datetime,
        limit: int = 100
    ) -> List[TradingPlan]:
        """Get historical plans.
        
        Args:
            start: Start datetime
            end: End datetime
            limit: Max number of plans
            
        Returns:
            List of TradingPlan objects
        """
        ...
    
    @abstractmethod
    def save_order(self, order: Order) -> None:
        """Save an order.
        
        Args:
            order: Order to save
        """
        ...
    
    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get an order by ID.
        
        Args:
            order_id: Order ID
            
        Returns:
            Order if found, None otherwise
        """
        ...
    
    @abstractmethod
    def save_position(self, position: Position) -> None:
        """Save/update a position.
        
        Args:
            position: Position to save
        """
        ...
    
    @abstractmethod
    def get_position(self, ticket: int) -> Optional[Position]:
        """Get a position by ticket.
        
        Args:
            ticket: Broker ticket ID
            
        Returns:
            Position if found, None otherwise
        """
        ...
    
    @abstractmethod
    def get_open_positions(self, symbol: str | None = None) -> List[Position]:
        """Get all open positions.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            List of open Position objects
        """
        ...
    
    @abstractmethod
    def get_closed_trades(
        self,
        start: datetime,
        end: datetime,
        limit: int = 100
    ) -> List[dict]:
        """Get closed trades for analysis.
        
        Args:
            start: Start datetime
            end: End datetime
            limit: Max number of trades
            
        Returns:
            List of closed trade dicts
        """
        ...
