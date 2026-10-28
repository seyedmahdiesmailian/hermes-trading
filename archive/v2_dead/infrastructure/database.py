"""Database Layer - SQLite for analytics and fast queries.

Replaces JSON files for:
- Trade history
- Performance metrics
- Pattern learning
- Fast analytics queries
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import contextmanager


class Database:
    """SQLite database for trading data."""
    
    def __init__(self, db_path: str = "data/hermes.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Access by column name
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_schema(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Plans table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    position_size REAL NOT NULL,
                    setup_grade TEXT,
                    stage TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    executed_at TEXT,
                    closed_at TEXT,
                    ticket INTEGER,
                    actual_entry_price REAL,
                    exit_price REAL,
                    profit REAL,
                    reasoning TEXT,
                    INDEX idx_symbol (symbol),
                    INDEX idx_stage (stage),
                    INDEX idx_created_at (created_at)
                )
            ''')
            
            # Trades table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    ticket INTEGER PRIMARY KEY,
                    plan_id TEXT,
                    symbol TEXT NOT NULL,
                    type TEXT NOT NULL,
                    volume REAL NOT NULL,
                    open_price REAL NOT NULL,
                    close_price REAL,
                    sl REAL,
                    tp REAL,
                    open_time TEXT NOT NULL,
                    close_time TEXT,
                    profit REAL,
                    commission REAL,
                    swap REAL,
                    duration_seconds INTEGER,
                    is_open BOOLEAN DEFAULT 1,
                    FOREIGN KEY (plan_id) REFERENCES plans(id),
                    INDEX idx_is_open (is_open),
                    INDEX idx_open_time (open_time)
                )
            ''')
            
            # Performance metrics table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    balance REAL,
                    equity REAL,
                    daily_pnl REAL,
                    total_trades INTEGER,
                    wins INTEGER,
                    losses INTEGER,
                    win_rate REAL,
                    profit_factor REAL,
                    sharpe_ratio REAL,
                    max_drawdown REAL,
                    INDEX idx_timestamp (timestamp)
                )
            ''')
            
            # Patterns table (for learning)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_hash TEXT UNIQUE NOT NULL,
                    setup_grade TEXT,
                    trend TEXT,
                    strength REAL,
                    outcome TEXT,
                    profit REAL,
                    created_at TEXT NOT NULL,
                    metadata TEXT,
                    INDEX idx_setup_grade (setup_grade),
                    INDEX idx_outcome (outcome)
                )
            ''')
            
            # Signals table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    source TEXT NOT NULL,
                    confidence_score REAL,
                    quality TEXT,
                    accepted BOOLEAN,
                    reasoning TEXT,
                    created_at TEXT NOT NULL,
                    INDEX idx_source (source),
                    INDEX idx_accepted (accepted),
                    INDEX idx_created_at (created_at)
                )
            ''')
    
    def save_plan(self, plan: Dict[str, Any]):
        """Save trading plan."""
        with self._get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO plans
                (id, symbol, direction, entry_price, stop_loss, take_profit,
                 position_size, setup_grade, stage, created_at, executed_at,
                 closed_at, ticket, actual_entry_price, exit_price, profit, reasoning)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                plan['id'],
                plan['symbol'],
                plan['direction'],
                plan['entry_price'],
                plan['stop_loss'],
                plan['take_profit'],
                plan['position_size'],
                plan.get('setup_grade'),
                plan['stage'],
                plan['created_at'],
                plan.get('executed_at'),
                plan.get('closed_at'),
                plan.get('ticket'),
                plan.get('actual_entry_price'),
                plan.get('exit_price'),
                plan.get('profit'),
                json.dumps(plan.get('reasoning', {}))
            ))
    
    def get_recent_plans(self, limit: int = 10) -> List[Dict]:
        """Get recent plans."""
        with self._get_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM plans
                ORDER BY created_at DESC
                LIMIT ?
            ''', (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_performance_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get performance statistics."""
        with self._get_connection() as conn:
            cursor = conn.execute('''
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN profit < 0 THEN 1 ELSE 0 END) as losses,
                    SUM(profit) as total_profit,
                    AVG(profit) as avg_profit,
                    MAX(profit) as max_profit,
                    MIN(profit) as min_profit
                FROM trades
                WHERE close_time >= datetime('now', '-' || ? || ' days')
                AND is_open = 0
            ''', (days,))
            
            row = cursor.fetchone()
            if row:
                stats = dict(row)
                if stats['total_trades'] > 0:
                    stats['win_rate'] = (stats['wins'] / stats['total_trades']) * 100
                else:
                    stats['win_rate'] = 0
                return stats
            
            return {}
    
    def save_pattern(self, pattern: Dict[str, Any]):
        """Save learned pattern."""
        with self._get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO patterns
                (pattern_hash, setup_grade, trend, strength, outcome,
                 profit, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                pattern['pattern_hash'],
                pattern.get('setup_grade'),
                pattern.get('trend'),
                pattern.get('strength'),
                pattern['outcome'],
                pattern.get('profit'),
                pattern['created_at'],
                json.dumps(pattern.get('metadata', {}))
            ))
    
    def query_patterns(self, setup_grade: Optional[str] = None) -> List[Dict]:
        """Query learned patterns."""
        with self._get_connection() as conn:
            if setup_grade:
                cursor = conn.execute('''
                    SELECT * FROM patterns
                    WHERE setup_grade = ?
                    ORDER BY created_at DESC
                ''', (setup_grade,))
            else:
                cursor = conn.execute('''
                    SELECT * FROM patterns
                    ORDER BY created_at DESC
                    LIMIT 100
                ''')
            
            return [dict(row) for row in cursor.fetchall()]
