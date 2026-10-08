"""JSON Repository — File-based data storage.

Implements repository interfaces using JSON files.
"""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
import fcntl

from brain.domain.entities.trade import Order, Position
from brain.domain.entities.plan import TradingPlan, SetupGrade, PlanStage
from brain.domain.entities.signal import Signal, SignalSource, SignalQuality
from brain.domain.entities.account import AccountState
from brain.domain.repositories.trade_repo import ITradeRepository
from brain.domain.repositories.signal_repo import ISignalRepository
from brain.domain.repositories.state_repo import IStateRepository


class JSONRepository(ITradeRepository, ISignalRepository, IStateRepository):
    """JSON file-based repository.
    
    Stores data in JSON files with file locking for safety.
    
    Structure:
    data/
    ├── plans/
    │   ├── current_plan.json
    │   └── history/
    │       └── plan_{id}.json
    ├── signals/
    │   ├── pending.json
    │   └── history/
    ├── state/
    │   ├── account.json
    │   ├── performance.json
    │   └── learning.json
    └── positions/
        └── {ticket}.json
    
    Usage:
        repo = JSONRepository(data_dir="/home/ai/hermes-trading/data")
        
        # Save plan
        repo.save_plan(plan)
        
        # Get active plan
        plan = repo.get_active_plan()
    """
    
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self._ensure_structure()
    
    def _ensure_structure(self):
        """Ensure directory structure exists."""
        dirs = [
            self.data_dir / 'plans' / 'history',
            self.data_dir / 'signals' / 'history',
            self.data_dir / 'state',
            self.data_dir / 'positions'
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
    
    def _read_json(self, path: Path, default: Any = None) -> Any:
        """Read JSON file with locking."""
        if not path.exists():
            return default
        
        try:
            with open(path, 'r') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    return json.load(f)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except (json.JSONDecodeError, IOError):
            return default
    
    def _write_json(self, path: Path, data: Any):
        """Write JSON file with locking."""
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2, default=str)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    
    # ========== Trade Repository ==========
    
    def save_plan(self, plan: TradingPlan) -> None:
        """Save a trading plan."""
        # Save to history
        history_path = self.data_dir / 'plans' / 'history' / f"plan_{plan.id}.json"
        self._write_json(history_path, self._plan_to_dict(plan))
        
        # If active, save as current
        if plan.stage in [PlanStage.READY, PlanStage.EXECUTED, PlanStage.MONITORING]:
            current_path = self.data_dir / 'plans' / 'current_plan.json'
            self._write_json(current_path, self._plan_to_dict(plan))
    
    def get_plan(self, plan_id: str) -> Optional[TradingPlan]:
        """Get a trading plan by ID."""
        path = self.data_dir / 'plans' / 'history' / f"plan_{plan_id}.json"
        data = self._read_json(path)
        return self._dict_to_plan(data) if data else None
    
    def get_active_plan(self) -> Optional[TradingPlan]:
        """Get the currently active plan."""
        path = self.data_dir / 'plans' / 'current_plan.json'
        data = self._read_json(path)
        return self._dict_to_plan(data) if data else None
    
    def get_plan_history(
        self,
        start: datetime,
        end: datetime,
        limit: int = 100
    ) -> List[TradingPlan]:
        """Get historical plans."""
        history_dir = self.data_dir / 'plans' / 'history'
        plans = []
        
        for file in sorted(history_dir.glob('plan_*.json'))[:limit]:
            data = self._read_json(file)
            if data:
                plan = self._dict_to_plan(data)
                if plan and start <= plan.created_at <= end:
                    plans.append(plan)
        
        return plans
    
    def save_order(self, order: Order) -> None:
        """Save an order."""
        path = self.data_dir / 'orders' / f"order_{order.id}.json"
        self._write_json(path, self._order_to_dict(order))
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get an order by ID."""
        path = self.data_dir / 'orders' / f"order_{order_id}.json"
        data = self._read_json(path)
        return self._dict_to_order(data) if data else None
    
    def save_position(self, position: Position) -> None:
        """Save/update a position."""
        path = self.data_dir / 'positions' / f"{position.ticket}.json"
        self._write_json(path, self._position_to_dict(position))
    
    def get_position(self, ticket: int) -> Optional[Position]:
        """Get a position by ticket."""
        path = self.data_dir / 'positions' / f"{ticket}.json"
        data = self._read_json(path)
        return self._dict_to_position(data) if data else None
    
    def get_open_positions(self, symbol: str | None = None) -> List[Position]:
        """Get all open positions."""
        positions_dir = self.data_dir / 'positions'
        positions = []
        
        for file in positions_dir.glob('*.json'):
            data = self._read_json(file)
            if data:
                position = self._dict_to_position(data)
                if position and (not symbol or position.order.symbol == symbol):
                    positions.append(position)
        
        return positions
    
    def get_closed_trades(
        self,
        start: datetime,
        end: datetime,
        limit: int = 100
    ) -> List[dict]:
        """Get closed trades."""
        # Placeholder - would read from closed_trades.json
        return []
    
    # ========== Signal Repository ==========
    
    def save_signal(self, signal: Signal) -> None:
        """Save a signal."""
        path = self.data_dir / 'signals' / 'history' / f"signal_{signal.id}.json"
        self._write_json(path, self._signal_to_dict(signal))
    
    def get_signal(self, signal_id: str) -> Optional[Signal]:
        """Get a signal by ID."""
        path = self.data_dir / 'signals' / 'history' / f"signal_{signal_id}.json"
        data = self._read_json(path)
        return self._dict_to_signal(data) if data else None
    
    def get_pending_signals(self) -> List[Signal]:
        """Get pending signals."""
        path = self.data_dir / 'signals' / 'pending.json'
        data = self._read_json(path, default=[])
        return [self._dict_to_signal(s) for s in data if s]
    
    def get_recent_signals(
        self,
        limit: int = 50,
        start: datetime | None = None
    ) -> List[Signal]:
        """Get recent signals."""
        history_dir = self.data_dir / 'signals' / 'history'
        signals = []
        
        for file in sorted(history_dir.glob('signal_*.json'), reverse=True)[:limit]:
            data = self._read_json(file)
            if data:
                signal = self._dict_to_signal(data)
                if signal and (not start or signal.timestamp >= start):
                    signals.append(signal)
        
        return signals
    
    def mark_signal_processed(self, signal_id: str, result: dict) -> None:
        """Mark signal as processed."""
        # Update signal in history
        path = self.data_dir / 'signals' / 'history' / f"signal_{signal_id}.json"
        data = self._read_json(path)
        if data:
            data['processed'] = True
            data['result'] = result
            self._write_json(path, data)
    
    # ========== State Repository ==========
    
    def save_account_state(self, state: AccountState) -> None:
        """Save account state."""
        path = self.data_dir / 'state' / 'account.json'
        self._write_json(path, self._account_state_to_dict(state))
    
    def get_account_state(self) -> Optional[AccountState]:
        """Get account state."""
        path = self.data_dir / 'state' / 'account.json'
        data = self._read_json(path)
        return self._dict_to_account_state(data) if data else None
    
    def save_performance_state(self, state: Dict[str, Any]) -> None:
        """Save performance metrics."""
        path = self.data_dir / 'state' / 'performance.json'
        self._write_json(path, state)
    
    def get_performance_state(self) -> Dict[str, Any]:
        """Get performance metrics."""
        path = self.data_dir / 'state' / 'performance.json'
        return self._read_json(path, default={})
    
    def save_learning_state(self, state: Dict[str, Any]) -> None:
        """Save learning state."""
        path = self.data_dir / 'state' / 'learning.json'
        self._write_json(path, state)
    
    def get_learning_state(self) -> Dict[str, Any]:
        """Get learning state."""
        path = self.data_dir / 'state' / 'learning.json'
        return self._read_json(path, default={})
    
    def save_system_state(self, key: str, value: Any) -> None:
        """Save system state."""
        path = self.data_dir / 'state' / 'system.json'
        data = self._read_json(path, default={})
        data[key] = value
        self._write_json(path, data)
    
    def get_system_state(self, key: str, default: Any = None) -> Any:
        """Get system state."""
        path = self.data_dir / 'state' / 'system.json'
        data = self._read_json(path, default={})
        return data.get(key, default)
    
    # ========== Conversion helpers ==========
    
    def _plan_to_dict(self, plan: TradingPlan) -> dict:
        """Convert TradingPlan to dict."""
        return {
            'id': plan.id,
            'symbol': plan.symbol,
            'direction': plan.direction,
            'entry_price': plan.entry_price,
            'stop_loss': plan.stop_loss,
            'take_profit': plan.take_profit,
            'position_size': plan.position_size,
            'setup_grade': plan.setup_grade.value,
            'reasoning': plan.reasoning,
            'created_at': plan.created_at.isoformat(),
            'stage': plan.stage.value,
            'executed_at': plan.executed_at.isoformat() if plan.executed_at else None,
            'closed_at': plan.closed_at.isoformat() if plan.closed_at else None,
            'ticket': plan.ticket,
            'actual_entry_price': plan.actual_entry_price,
            'exit_price': plan.exit_price,
            'profit': plan.profit
        }
    
    def _dict_to_plan(self, data: dict) -> TradingPlan:
        """Convert dict to TradingPlan."""
        # Simplified conversion - would need full implementation
        return None  # Placeholder
    
    def _order_to_dict(self, order: Order) -> dict:
        """Convert Order to dict."""
        return {
            'id': order.id,
            'symbol': order.symbol,
            'type': order.type.value,
            'volume': order.volume,
            'entry_price': order.entry_price,
            'stop_loss': order.stop_loss,
            'take_profit': order.take_profit,
            'comment': order.comment,
            'timestamp': order.timestamp.isoformat(),
            'status': order.status.value
        }
    
    def _dict_to_order(self, data: dict) -> Order:
        """Convert dict to Order."""
        return None  # Placeholder
    
    def _position_to_dict(self, position: Position) -> dict:
        """Convert Position to dict."""
        return {
            'ticket': position.ticket,
            'order': self._order_to_dict(position.order),
            'open_time': position.open_time.isoformat(),
            'open_price': position.open_price,
            'current_price': position.current_price,
            'profit': position.profit,
            'max_profit': position.max_profit,
            'max_loss': position.max_loss
        }
    
    def _dict_to_position(self, data: dict) -> Position:
        """Convert dict to Position."""
        return None  # Placeholder
    
    def _signal_to_dict(self, signal: Signal) -> dict:
        """Convert Signal to dict."""
        return {
            'id': signal.id,
            'symbol': signal.symbol,
            'direction': signal.direction,
            'entry_price': signal.entry_price,
            'stop_loss': signal.stop_loss,
            'take_profit': signal.take_profit,
            'source': signal.source.value,
            'timestamp': signal.timestamp.isoformat(),
            'raw_message': signal.raw_message,
            'source_id': signal.source_id,
            'confidence_score': signal.confidence_score,
            'quality': signal.quality.value
        }
    
    def _dict_to_signal(self, data: dict) -> Signal:
        """Convert dict to Signal."""
        return None  # Placeholder
    
    def _account_state_to_dict(self, state: AccountState) -> dict:
        """Convert AccountState to dict."""
        return {
            'balance': state.balance,
            'equity': state.equity,
            'margin_free': state.margin_free,
            'margin_used': state.margin_used,
            'open_positions': state.open_positions,
            'open_positions_volume': state.open_positions_volume,
            'daily_pnl': state.daily_pnl,
            'daily_trades': state.daily_trades,
            'daily_wins': state.daily_wins,
            'daily_losses': state.daily_losses,
            'timestamp': state.timestamp.isoformat() if state.timestamp else None
        }
    
    def _dict_to_account_state(self, data: dict) -> AccountState:
        """Convert dict to AccountState."""
        return None  # Placeholder
    
    def __repr__(self) -> str:
        return f"JSONRepository({self.data_dir})"
