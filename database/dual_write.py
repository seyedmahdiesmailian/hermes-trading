"""Dual-write layer: JSON + Database.

Transition layer that writes to both legacy JSON files and new database.
Allows safe migration without breaking existing system.

Usage:
    from database.dual_write import DualWriteManager
    
    mgr = DualWriteManager()
    mgr.save_plan(plan)  # Writes to both JSON and DB
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from .db import Database, get_db


class DualWriteManager:
    """Manager for dual-write operations.
    
    Writes to both JSON files (legacy) and Database (new).
    Reads from Database by default, falls back to JSON.
    """
    
    def __init__(self, data_dir: Path = None, db: Database = None):
        """Initialize dual-write manager.
        
        Args:
            data_dir: Legacy data directory (default: data/)
            db: Database instance (default: singleton)
        """
        if data_dir is None:
            data_dir = Path(__file__).parent.parent / 'data'
        
        self.data_dir = Path(data_dir)
        self.db = db or get_db()
        
        # Ensure directories exist
        (self.data_dir / 'xau_plan').mkdir(parents=True, exist_ok=True)
        (self.data_dir / 'signals').mkdir(parents=True, exist_ok=True)
    
    # ========================================================================
    # PLANS
    # ========================================================================
    
    def save_plan(self, plan: Dict[str, Any]) -> int:
        """Save plan to both JSON and Database.
        
        Args:
            plan: Plan dictionary
            
        Returns:
            Database row ID
        """
        # 1. Write to JSON (legacy)
        plan_file = self.data_dir / 'xau_plan' / 'current_plan.json'
        try:
            with plan_file.open('w') as f:
                json.dump(plan, f, indent=2, default=str)
        except Exception as e:
            print(f"⚠️ JSON write failed: {e}")
        
        # 2. Write to Database (new)
        try:
            return self.db.save_plan(plan)
        except Exception as e:
            print(f"❌ Database write failed: {e}")
            raise
    
    def get_current_plan(self) -> Optional[Dict[str, Any]]:
        """Get current plan (DB first, JSON fallback).
        
        Returns:
            Plan dict or None
        """
        # Try Database first
        try:
            plan = self.db.get_current_plan()
            if plan:
                return plan
        except Exception as e:
            print(f"⚠️ Database read failed: {e}")
        
        # Fallback to JSON
        plan_file = self.data_dir / 'xau_plan' / 'current_plan.json'
        if plan_file.exists():
            try:
                with plan_file.open() as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ JSON read failed: {e}")
        
        return None
    
    # ========================================================================
    # TRADES
    # ========================================================================
    
    def save_trade(self, trade: Dict[str, Any]) -> int:
        """Save trade to both CSV and Database.
        
        Args:
            trade: Trade dictionary
            
        Returns:
            Database row ID
        """
        # 1. Append to CSV (legacy)
        csv_file = self.data_dir / 'xau_plan' / 'execution_log.csv'
        try:
            import csv
            
            # Check if file exists (need header?)
            write_header = not csv_file.exists()
            
            with csv_file.open('a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'at', 'source', 'plan_id', 'action', 'side', 'lot',
                    'entry', 'sl', 'tp', 'grade', 'risk_usd', 'dry_run',
                    'result_ok', 'ticket'
                ])
                
                if write_header:
                    writer.writeheader()
                
                # Map to legacy format
                writer.writerow({
                    'at': datetime.fromtimestamp(trade['entry_time'], tz=timezone.utc).isoformat(),
                    'source': trade.get('source', ''),
                    'plan_id': trade.get('source_ref', ''),
                    'action': 'market',
                    'side': trade['side'].upper(),
                    'lot': trade['volume'],
                    'entry': trade['entry_price'],
                    'sl': trade.get('stop_loss', ''),
                    'tp': trade.get('take_profit', ''),
                    'grade': '',
                    'risk_usd': '',
                    'dry_run': 'False',
                    'result_ok': 'True',
                    'ticket': trade['ticket']
                })
        except Exception as e:
            print(f"⚠️ CSV write failed: {e}")
        
        # 2. Write to Database (new)
        try:
            return self.db.save_trade(trade)
        except Exception as e:
            print(f"❌ Database write failed: {e}")
            raise
    
    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Get open trades from Database.
        
        Returns:
            List of trade dicts
        """
        return self.db.get_open_trades()
    
    def close_trade(self, ticket: int, exit_price: float, profit: float,
                   exit_reason: str, commission: float = 0, swap: float = 0) -> int:
        """Close trade in Database.
        
        Note: Legacy CSV is append-only, no updates needed.
        
        Args:
            ticket: Trade ticket
            exit_price: Exit price
            profit: Gross profit
            exit_reason: Reason for exit
            commission: Commission paid
            swap: Swap
            
        Returns:
            Number of rows updated
        """
        return self.db.close_trade(
            ticket, exit_price, profit, exit_reason, commission, swap
        )
    
    # ========================================================================
    # SIGNALS
    # ========================================================================
    
    def save_signal(self, signal: Dict[str, Any]) -> int:
        """Save signal to both JSON and Database.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Database row ID
        """
        # 1. Write to JSON (legacy)
        signal_file = self.data_dir / 'signals' / f"{signal['signal_id']}.json"
        try:
            with signal_file.open('w') as f:
                json.dump(signal, f, indent=2, default=str)
        except Exception as e:
            print(f"⚠️ JSON write failed: {e}")
        
        # 2. Write to Database (new)
        try:
            return self.db.save_signal(signal)
        except Exception as e:
            print(f"❌ Database write failed: {e}")
            raise
    
    def get_pending_signals(self) -> List[Dict[str, Any]]:
        """Get pending signals (DB first, JSON fallback).
        
        Returns:
            List of signal dicts
        """
        # Try Database first
        try:
            signals = self.db.get_pending_signals()
            if signals:
                return signals
        except Exception as e:
            print(f"⚠️ Database read failed: {e}")
        
        # Fallback to JSON
        signals = []
        signals_dir = self.data_dir / 'signals'
        if signals_dir.exists():
            for signal_file in signals_dir.glob('*.json'):
                try:
                    with signal_file.open() as f:
                        signal = json.load(f)
                        if signal.get('status') == 'pending':
                            signals.append(signal)
                except Exception as e:
                    print(f"⚠️ Failed to read {signal_file}: {e}")
        
        return signals
    
    def update_signal_status(self, signal_id: str, status: str,
                           reasoning: str = None) -> int:
        """Update signal status in Database.
        
        Note: Legacy JSON files are not updated (append-only pattern).
        
        Args:
            signal_id: Signal ID
            status: New status
            reasoning: Decision reasoning
            
        Returns:
            Number of rows updated
        """
        return self.db.update_signal_status(signal_id, status, reasoning)
    
    # ========================================================================
    # STATE
    # ========================================================================
    
    def get_risk_state(self) -> Dict[str, Any]:
        """Get risk state from Database."""
        return self.db.get_risk_state()
    
    def update_risk_state(self, state: Dict[str, Any]) -> int:
        """Update risk state in Database."""
        return self.db.update_risk_state(state)
    
    def log_safety_event(self, event_type: str, severity: str,
                        message: str, data: Dict = None) -> int:
        """Log safety event to Database."""
        return self.db.log_safety_event(event_type, severity, message, data)
    
    # ========================================================================
    # JOURNAL
    # ========================================================================
    
    def save_journal_entry(self, entry: Dict[str, Any]) -> int:
        """Save journal entry to both CSV and Database.
        
        Args:
            entry: Journal entry dict
            
        Returns:
            Database row ID
        """
        # 1. Append to CSV (legacy)
        csv_file = self.data_dir / 'xau_plan' / 'trade_journal.csv'
        try:
            import csv
            
            write_header = not csv_file.exists()
            
            with csv_file.open('a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'ticket', 'grade', 'style', 'session', 'profit',
                    'exit_type', 'close_time', 'comment'
                ])
                
                if write_header:
                    writer.writeheader()
                
                writer.writerow({
                    'ticket': entry['ticket'],
                    'grade': entry.get('setup_grade', ''),
                    'style': entry.get('setup_style', ''),
                    'session': entry.get('session', ''),
                    'profit': entry.get('net_pnl', ''),
                    'exit_type': entry.get('exit_type', ''),
                    'close_time': entry['close_time'],
                    'comment': entry.get('notes', '')
                })
        except Exception as e:
            print(f"⚠️ CSV write failed: {e}")
        
        # 2. Write to Database (new)
        try:
            return self.db.execute(
                """INSERT INTO trade_journal (
                    ticket, setup_grade, setup_style, session,
                    net_pnl, exit_type, close_time, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry['ticket'],
                    entry.get('setup_grade'),
                    entry.get('setup_style'),
                    entry.get('session'),
                    entry.get('net_pnl'),
                    entry.get('exit_type'),
                    entry['close_time'],
                    entry.get('notes')
                )
            )
        except Exception as e:
            print(f"❌ Database write failed: {e}")
            raise


# Singleton instance
_dual_write_instance = None

def get_dual_write() -> DualWriteManager:
    """Get singleton dual-write manager instance."""
    global _dual_write_instance
    if _dual_write_instance is None:
        _dual_write_instance = DualWriteManager()
    return _dual_write_instance
