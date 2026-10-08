"""Signal Repository Interface.

Defines how the domain stores and retrieves signals.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime

from brain.domain.entities.signal import Signal


class ISignalRepository(ABC):
    """Signal repository interface.
    
    Stores signals from Telegram or other sources.
    """
    
    @abstractmethod
    def save_signal(self, signal: Signal) -> None:
        """Save a signal.
        
        Args:
            signal: Signal to save
        """
        ...
    
    @abstractmethod
    def get_signal(self, signal_id: str) -> Optional[Signal]:
        """Get a signal by ID.
        
        Args:
            signal_id: Signal ID
            
        Returns:
            Signal if found, None otherwise
        """
        ...
    
    @abstractmethod
    def get_pending_signals(self) -> List[Signal]:
        """Get signals awaiting processing.
        
        Returns:
            List of pending Signal objects
        """
        ...
    
    @abstractmethod
    def get_recent_signals(
        self,
        limit: int = 50,
        start: datetime | None = None
    ) -> List[Signal]:
        """Get recent signals.
        
        Args:
            limit: Max number of signals
            start: Optional start time
            
        Returns:
            List of Signal objects
        """
        ...
    
    @abstractmethod
    def mark_signal_processed(self, signal_id: str, result: dict) -> None:
        """Mark signal as processed with result.
        
        Args:
            signal_id: Signal ID
            result: Processing result dict
        """
        ...
