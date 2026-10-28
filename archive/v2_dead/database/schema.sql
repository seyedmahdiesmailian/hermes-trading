-- Hermes Trading Database Schema
-- Central database for all trading state, history, and configuration
-- Engine: SQLite (for now) → PostgreSQL (future)
-- Created: 2026-10-15

-- ============================================================================
-- MARKET DATA & ANALYSIS
-- ============================================================================

-- Market snapshots (OHLCV data)
CREATE TABLE IF NOT EXISTS market_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,  -- M5, M15, H1, H4, D1
    timestamp INTEGER NOT NULL,  -- Unix timestamp
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    UNIQUE(symbol, timeframe, timestamp)
);
CREATE INDEX idx_market_data_symbol_tf ON market_data(symbol, timeframe, timestamp DESC);

-- Trading plans (analysis results)
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT UNIQUE NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    bias TEXT NOT NULL,  -- bullish, bearish, neutral
    session TEXT,  -- asia, london, newyork
    
    -- Zones
    value_low REAL,
    value_high REAL,
    long_entry_low REAL,
    long_entry_high REAL,
    short_entry_low REAL,
    short_entry_high REAL,
    
    -- Context
    atr REAL,
    grade TEXT,  -- A, B, C
    setup_score REAL,
    
    -- Metadata
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    status TEXT DEFAULT 'active',  -- active, executed, expired
    
    -- Analysis JSON (detailed context)
    analysis_json TEXT,  -- JSON blob
    
    UNIQUE(plan_id)
);
CREATE INDEX idx_plans_symbol ON plans(symbol, created_at DESC);
CREATE INDEX idx_plans_status ON plans(status, created_at DESC);

-- ============================================================================
-- SIGNALS (Telegram & Internal)
-- ============================================================================

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT UNIQUE NOT NULL,
    
    -- Core data
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,  -- buy, sell
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    
    -- Source
    source TEXT NOT NULL,  -- telegram, internal, hybrid
    source_id TEXT,  -- message ID or reference
    raw_message TEXT,
    
    -- Quality
    confidence_score REAL,
    quality TEXT,  -- excellent, good, acceptable, poor, rejected
    
    -- Processing
    status TEXT DEFAULT 'pending',  -- pending, accepted, rejected, executed
    processed_at INTEGER,
    decision_reasoning TEXT,
    
    -- Timestamps
    received_at INTEGER NOT NULL,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    
    UNIQUE(signal_id)
);
CREATE INDEX idx_signals_status ON signals(status, received_at DESC);
CREATE INDEX idx_signals_symbol ON signals(symbol, received_at DESC);

-- ============================================================================
-- TRADES & POSITIONS
-- ============================================================================

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- MT5 identifiers
    ticket INTEGER UNIQUE NOT NULL,
    position_id INTEGER,
    
    -- Trade data
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,  -- buy, sell
    volume REAL NOT NULL,
    
    -- Prices
    entry_price REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    exit_price REAL,
    
    -- P&L
    profit REAL,
    commission REAL,
    swap REAL,
    net_pnl REAL,
    
    -- Source
    source TEXT,  -- plan_id, signal_id, manual
    source_ref TEXT,  -- reference to plan or signal
    
    -- Timing
    entry_time INTEGER NOT NULL,
    exit_time INTEGER,
    duration_seconds INTEGER,
    
    -- Status
    status TEXT DEFAULT 'open',  -- open, closed
    exit_reason TEXT,  -- sl, tp, manual, managed, trail
    
    -- Metadata
    comment TEXT,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX idx_trades_status ON trades(status, entry_time DESC);
CREATE INDEX idx_trades_symbol ON trades(symbol, entry_time DESC);
CREATE INDEX idx_trades_source ON trades(source, source_ref);

-- Position management state
CREATE TABLE IF NOT EXISTS position_state (
    ticket INTEGER PRIMARY KEY,
    
    -- Tracking
    mfe REAL,  -- Max Favorable Excursion
    mae REAL,  -- Max Adverse Excursion
    
    -- Management actions
    breakeven_moved BOOLEAN DEFAULT 0,
    partial_tp_count INTEGER DEFAULT 0,
    trail_active BOOLEAN DEFAULT 0,
    
    -- Last check
    last_check_at INTEGER,
    last_price REAL,
    
    updated_at INTEGER DEFAULT (strftime('%s', 'now')),
    
    FOREIGN KEY (ticket) REFERENCES trades(ticket)
);

-- ============================================================================
-- ACCOUNT & PERFORMANCE
-- ============================================================================

CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Account state
    balance REAL NOT NULL,
    equity REAL NOT NULL,
    margin REAL,
    margin_free REAL,
    
    -- Positions
    open_positions INTEGER DEFAULT 0,
    
    -- Performance
    daily_pnl REAL,
    daily_trades INTEGER,
    win_rate REAL,
    
    -- Timestamp
    snapshot_at INTEGER NOT NULL,
    created_at INTEGER DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX idx_account_snapshots_time ON account_snapshots(snapshot_at DESC);

-- Performance metrics (daily summary)
CREATE TABLE IF NOT EXISTS daily_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,  -- YYYY-MM-DD
    
    -- P&L
    gross_pnl REAL,
    net_pnl REAL,
    commission_total REAL,
    swap_total REAL,
    
    -- Trades
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    win_rate REAL,
    
    -- Risk
    max_drawdown REAL,
    avg_win REAL,
    avg_loss REAL,
    profit_factor REAL,
    
    created_at INTEGER DEFAULT (strftime('%s', 'now'))
);

-- ============================================================================
-- RISK & SAFETY
-- ============================================================================

CREATE TABLE IF NOT EXISTS risk_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- DEFCON level
    defcon_level TEXT NOT NULL,  -- GREEN, YELLOW, RED
    
    -- Counters
    loss_streak INTEGER DEFAULT 0,
    daily_loss_pct REAL,
    
    -- Kill switches
    kill_switch_active BOOLEAN DEFAULT 0,
    cooldown_until INTEGER,
    
    -- Learning multipliers
    risk_multiplier REAL DEFAULT 1.0,
    min_grade TEXT,
    
    -- Timestamp
    effective_at INTEGER NOT NULL,
    created_at INTEGER DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX idx_risk_state_time ON risk_state(effective_at DESC);

-- Safety events log
CREATE TABLE IF NOT EXISTS safety_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,  -- kill_switch, cooldown, defcon_change
    severity TEXT NOT NULL,  -- info, warning, critical
    message TEXT NOT NULL,
    data_json TEXT,  -- Additional context
    created_at INTEGER DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX idx_safety_events_time ON safety_events(created_at DESC);

-- ============================================================================
-- LEARNING & JOURNAL
-- ============================================================================

CREATE TABLE IF NOT EXISTS trade_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket INTEGER NOT NULL,
    
    -- Classification
    setup_grade TEXT,
    setup_style TEXT,
    session TEXT,
    
    -- Outcome
    net_pnl REAL,
    rr_realized REAL,
    exit_type TEXT,  -- sl, tp, managed, trail
    
    -- Context
    plan_id TEXT,
    signal_id TEXT,
    
    -- Metrics
    mfe REAL,
    mae REAL,
    duration_minutes INTEGER,
    
    -- Lesson
    notes TEXT,
    
    -- Timestamp
    close_time INTEGER NOT NULL,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    
    FOREIGN KEY (ticket) REFERENCES trades(ticket)
);
CREATE INDEX idx_journal_grade ON trade_journal(setup_grade, close_time DESC);
CREATE INDEX idx_journal_session ON trade_journal(session, close_time DESC);

-- Learning adjustments
CREATE TABLE IF NOT EXISTS learning_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parameter TEXT NOT NULL,
    old_value REAL,
    new_value REAL NOT NULL,
    reason TEXT,
    sample_size INTEGER,
    applied_at INTEGER NOT NULL,
    created_at INTEGER DEFAULT (strftime('%s', 'now'))
);

-- ============================================================================
-- CONFIGURATION
-- ============================================================================

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    data_type TEXT DEFAULT 'string',  -- string, int, float, bool, json
    description TEXT,
    updated_at INTEGER DEFAULT (strftime('%s', 'now'))
);

-- Insert default config
INSERT OR IGNORE INTO config (key, value, data_type, description) VALUES
    ('max_risk_per_trade', '0.02', 'float', 'Maximum risk per trade (2%)'),
    ('min_risk_reward', '2.0', 'float', 'Minimum RR ratio'),
    ('max_daily_loss', '0.05', 'float', 'Maximum daily loss (5%)'),
    ('max_daily_trades', '5', 'int', 'Maximum trades per day'),
    ('max_open_positions', '1', 'int', 'Maximum simultaneous positions'),
    ('min_setup_grade', 'B', 'string', 'Minimum setup grade to execute');

-- ============================================================================
-- SYSTEM STATE
-- ============================================================================

CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER DEFAULT (strftime('%s', 'now'))
);

-- Initialize system state
INSERT OR IGNORE INTO system_state (key, value) VALUES
    ('last_master_run', '0'),
    ('last_position_check', '0'),
    ('last_signal_check', '0'),
    ('bridge_last_healthy', '0'),
    ('dry_run', 'true');

-- ============================================================================
-- VIEWS (Convenience queries)
-- ============================================================================

-- Active trades
CREATE VIEW IF NOT EXISTS v_active_trades AS
SELECT 
    t.*,
    ps.mfe,
    ps.mae,
    ps.breakeven_moved,
    ps.trail_active
FROM trades t
LEFT JOIN position_state ps ON t.ticket = ps.ticket
WHERE t.status = 'open';

-- Recent performance (last 30 days)
CREATE VIEW IF NOT EXISTS v_recent_performance AS
SELECT 
    date,
    net_pnl,
    total_trades,
    win_rate,
    profit_factor
FROM daily_performance
WHERE date >= date('now', '-30 days')
ORDER BY date DESC;

-- Latest plan
CREATE VIEW IF NOT EXISTS v_current_plan AS
SELECT *
FROM plans
WHERE status = 'active'
  AND expires_at > strftime('%s', 'now')
ORDER BY created_at DESC
LIMIT 1;

-- ============================================================================
-- DONE
-- ============================================================================
