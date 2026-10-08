"""State Repository Interface.

Defines how the domain stores and retrieves system state.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from brain.domain.entities.account import AccountState


class IStateRepository(ABC):
    """State repository interface.
    
    Stores:
    - Account state
    - Performance metrics
    - Learning patterns
    - System state
    """
    
    @abstractmethod
    def save_account_state(self, state: AccountState) -> None:
        """Save account state snapshot.
        
        Args:
            state: Account state
        """
        ...
    
    @abstractmethod
    def get_account_state(self) -> Optional[AccountState]:
        """Get latest account state.
        
        Returns:
            AccountState if available, None otherwise
        """
        ...
    
    @abstractmethod
    def save_performance_state(self, state: Dict[str, Any]) -> None:
        """Save performance metrics.
        
        Args:
            state: Performance state dict
        """
        ...
    
    @abstractmethod
    def get_performance_state(self) -> Dict[str, Any]:
        """Get performance metrics.
        
        Returns:
            Performance state dict
        """
        ...
    
    @abstractmethod
    def save_learning_state(self, state: Dict[str, Any]) -> None:
        """Save learning patterns and history.
        
        Args:
            state: Learning state dict
        """
        ...
    
    @abstractmethod
    def get_learning_state(self) -> Dict[str, Any]:
        """Get learning patterns and history.
        
        Returns:
            Learning state dict
        """
        ...
    
    @abstractmethod
    def save_system_state(self, key: str, value: Any) -> None:
        """Save arbitrary system state.
        
        Args:
            key: State key
            value: State value
        """
        ...
    
    @abstractmethod
    def get_system_state(self, key: str, default: Any = None) -> Any:
        """Get system state by key.
        
        Args:
            key: State key
            default: Default value if not found
            
        Returns:
            State value or default
        """
        ...
