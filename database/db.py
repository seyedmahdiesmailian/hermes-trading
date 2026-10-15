"""Database wrapper for Hermes Trading System.

Centralized database access layer using SQLite.
Provides clean interface for all data operations.

Usage:
    from database.db import Database
    
    db = Database()
    db.execute("INSERT INTO trades ...")
    trades = db.fetch_all("SELECT * FROM trades WHERE status = 'open'")
"""

import sqlite3
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from contextlib import contextmanager
from datetime import datetime, timezone


class Database:
    """SQLite database wrapper."""
    
    def __init__(self, db_path: str = None):
        """Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file.
                    Defaults to data/hermes.db
        """
        if db_path is None:
            root = Path(__file__).parent.parent
            db_path = root / 'data' / 'hermes.db'
        
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize schema if needed
        if not self.db_path.exists():
            self._initialize_schema()
    
    def _initialize_schema(self):
        """Initialize database schema from schema.sql."""
        schema_path = Path(__file__).parent / 'schema.sql'
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        
        schema = schema_path.read_text(encoding='utf-8')
        
        with self.get_connection() as conn:
            conn.executescript(schema)
            conn.commit()
    
    @contextmanager
    def get_connection(self):
        """Get database connection context manager.
        
        Yields:
            sqlite3.Connection
        """
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row  # Access columns by name
        try:
            yield conn
        finally:
            conn.close()
    
    def execute(self, query: str, params: Tuple = ()) -> int:
        """Execute a query and return last row ID.
        
        Args:
            query: SQL query
            params: Query parameters
            
        Returns:
            Last inserted row ID
        """
        with self.get_connection() as conn:
            cursor = conn.execute(query, params)
            conn.commit()
            return cursor.lastrowid
    
    def execute_many(self, query: str, params_list: List[Tuple]) -> int:
        """Execute query with multiple parameter sets.
        
        Args:
            query: SQL query
            params_list: List of parameter tuples
            
        Returns:
            Number of affected rows
        """
        with self.get_connection() as conn:
            cursor = conn.executemany(query, params_list)
            conn.commit()
            return cursor.rowcount
    
    def fetch_one(self, query: str, params: Tuple = ()) -> Optional[Dict[str, Any]]:
        """Fetch single row.
        
        Args:
            query: SQL query
            params: Query parameters
            
        Returns:
            Dict of column values or None
        """
        with self.get_connection() as conn:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def fetch_all(self, query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
        """Fetch all rows.
        
        Args:
            query: SQL query
            params: Query parameters
            
        Returns:
            List of dicts
        """
        with self.get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    # ========================================================================
    # HIGH-LEVEL API
    # ========================================================================
    
    def get_current_plan(self) -> Optional[Dict[str, Any]]:
        """Get current active plan."""
        now = int(datetime.now(timezone.utc).timestamp())
        return self.fetch_one(
            "SELECT * FROM plans WHERE status = 'active' AND expires_at > ? "
            "ORDER BY created_at DESC LIMIT 1",
            (now,)
        )
    
    def save_plan(self, plan: Dict[str, Any]) -> int:
        """Save trading plan."""
        return self.execute(
            """INSERT INTO plans (
                plan_id, symbol, timeframe, bias, session,
                value_low, value_high, 
                long_entry_low, long_entry_high,
                short_entry_low, short_entry_high,
                atr, grade, setup_score,
                created_at, expires_at, status, analysis_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                plan['plan_id'], plan['symbol'], plan.get('timeframe', 'M5'),
                plan['bias'], plan.get('session'),
                plan.get('value_low'), plan.get('value_high'),
                plan.get('long_entry_low'), plan.get('long_entry_high'),
                plan.get('short_entry_low'), plan.get('short_entry_high'),
                plan.get('atr'), plan.get('grade'), plan.get('setup_score'),
                plan['created_at'], plan['expires_at'], 
                plan.get('status', 'active'),
                json.dumps(plan.get('analysis', {}))
            )
        )
    
    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Get all open trades."""
        return self.fetch_all(
            "SELECT * FROM v_active_trades ORDER BY entry_time DESC"
        )
    
    def save_trade(self, trade: Dict[str, Any]) -> int:
        """Save new trade."""
        return self.execute(
            """INSERT INTO trades (
                ticket, position_id, symbol, side, volume,
                entry_price, stop_loss, take_profit,
                source, source_ref, entry_time, status, comment
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade['ticket'], trade.get('position_id'),
                trade['symbol'], trade['side'], trade['volume'],
                trade['entry_price'], trade.get('stop_loss'), trade.get('take_profit'),
                trade.get('source'), trade.get('source_ref'),
                trade['entry_time'], trade.get('status', 'open'),
                trade.get('comment')
            )
        )
    
    def update_trade(self, ticket: int, updates: Dict[str, Any]) -> int:
        """Update trade."""
        set_clause = ', '.join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [ticket]
        
        return self.execute(
            f"UPDATE trades SET {set_clause}, updated_at = strftime('%s', 'now') "
            f"WHERE ticket = ?",
            tuple(values)
        )
    
    def close_trade(self, ticket: int, exit_price: float, profit: float, 
                   exit_reason: str, commission: float = 0, swap: float = 0) -> int:
        """Close a trade."""
        now = int(datetime.now(timezone.utc).timestamp())
        net_pnl = profit + commission + swap
        
        return self.execute(
            """UPDATE trades SET 
                exit_price = ?, profit = ?, commission = ?, swap = ?, 
                net_pnl = ?, exit_reason = ?, status = 'closed', 
                exit_time = ?, updated_at = strftime('%s', 'now')
            WHERE ticket = ?""",
            (exit_price, profit, commission, swap, net_pnl, exit_reason, now, ticket)
        )
    
    def save_signal(self, signal: Dict[str, Any]) -> int:
        """Save trading signal."""
        return self.execute(
            """INSERT INTO signals (
                signal_id, symbol, direction, entry_price, stop_loss, take_profit,
                source, source_id, raw_message, confidence_score, quality,
                status, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal['signal_id'], signal['symbol'], signal['direction'],
                signal['entry_price'], signal['stop_loss'], signal['take_profit'],
                signal['source'], signal.get('source_id'), signal.get('raw_message'),
                signal.get('confidence_score', 0.5), signal.get('quality', 'acceptable'),
                signal.get('status', 'pending'), signal['received_at']
            )
        )
    
    def update_signal_status(self, signal_id: str, status: str, 
                           reasoning: str = None) -> int:
        """Update signal processing status."""
        now = int(datetime.now(timezone.utc).timestamp())
        return self.execute(
            """UPDATE signals SET 
                status = ?, processed_at = ?, decision_reasoning = ?
            WHERE signal_id = ?""",
            (status, now, reasoning, signal_id)
        )
    
    def get_pending_signals(self) -> List[Dict[str, Any]]:
        """Get pending signals."""
        return self.fetch_all(
            "SELECT * FROM signals WHERE status = 'pending' "
            "ORDER BY received_at ASC"
        )
    
    def get_daily_pnl(self, date: str = None) -> float:
        """Get daily P&L.
        
        Args:
            date: Date in YYYY-MM-DD format (default: today)
            
        Returns:
            Net P&L for the day
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        
        result = self.fetch_one(
            "SELECT net_pnl FROM daily_performance WHERE date = ?",
            (date,)
        )
        return result['net_pnl'] if result else 0.0
    
    def get_risk_state(self) -> Dict[str, Any]:
        """Get current risk state."""
        return self.fetch_one(
            "SELECT * FROM risk_state ORDER BY effective_at DESC LIMIT 1"
        ) or {
            'defcon_level': 'GREEN',
            'loss_streak': 0,
            'risk_multiplier': 1.0
        }
    
    def update_risk_state(self, state: Dict[str, Any]) -> int:
        """Update risk state."""
        now = int(datetime.now(timezone.utc).timestamp())
        return self.execute(
            """INSERT INTO risk_state (
                defcon_level, loss_streak, daily_loss_pct,
                kill_switch_active, cooldown_until,
                risk_multiplier, min_grade, effective_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                state.get('defcon_level', 'GREEN'),
                state.get('loss_streak', 0),
                state.get('daily_loss_pct', 0),
                state.get('kill_switch_active', 0),
                state.get('cooldown_until'),
                state.get('risk_multiplier', 1.0),
                state.get('min_grade'),
                now
            )
        )
    
    def log_safety_event(self, event_type: str, severity: str, 
                        message: str, data: Dict = None) -> int:
        """Log safety event."""
        return self.execute(
            """INSERT INTO safety_events (event_type, severity, message, data_json)
            VALUES (?, ?, ?, ?)""",
            (event_type, severity, message, json.dumps(data) if data else None)
        )
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        result = self.fetch_one("SELECT value, data_type FROM config WHERE key = ?", (key,))
        if not result:
            return default
        
        value = result['value']
        dtype = result['data_type']
        
        # Type conversion
        if dtype == 'int':
            return int(value)
        elif dtype == 'float':
            return float(value)
        elif dtype == 'bool':
            return value.lower() in ('true', '1', 'yes')
        elif dtype == 'json':
            return json.loads(value)
        else:
            return value
    
    def set_config(self, key: str, value: Any, data_type: str = 'string') -> int:
        """Set configuration value."""
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
            data_type = 'json'
        else:
            value = str(value)
        
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO config (key, value, data_type) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = ?, data_type = ?, 
                updated_at = strftime('%s', 'now')""",
                (key, value, data_type, value, data_type)
            )
            conn.commit()
            return conn.total_changes


# Singleton instance
_db_instance = None

def get_db() -> Database:
    """Get singleton database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
