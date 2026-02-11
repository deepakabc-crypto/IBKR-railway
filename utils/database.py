"""
Trade Database Manager - SQLite storage for all trade records and P&L tracking.
"""
import sqlite3
import json
import os
from datetime import datetime, date
from typing import List, Dict, Optional
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "data/trades.db")


def get_db_path():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return DB_PATH


@contextmanager
def get_connection():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Initialize database tables."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL DEFAULT 'iron_condor',
                status TEXT NOT NULL DEFAULT 'open',
                
                -- Iron Condor Legs
                short_put_strike REAL,
                long_put_strike REAL,
                short_call_strike REAL,
                long_call_strike REAL,
                expiration TEXT,
                
                -- Pricing
                entry_credit REAL,
                exit_debit REAL,
                contracts INTEGER DEFAULT 1,
                
                -- Risk
                max_risk REAL,
                max_profit REAL,
                
                -- P&L
                realized_pnl REAL DEFAULT 0,
                unrealized_pnl REAL DEFAULT 0,
                commissions REAL DEFAULT 0,
                
                -- Timestamps
                entry_time TEXT,
                exit_time TEXT,
                exit_reason TEXT,
                
                -- Greeks at entry
                entry_delta REAL,
                entry_theta REAL,
                entry_vega REAL,
                entry_iv REAL,
                
                -- Metadata
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS daily_pnl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                realized_pnl REAL DEFAULT 0,
                unrealized_pnl REAL DEFAULT 0,
                total_pnl REAL DEFAULT 0,
                portfolio_value REAL DEFAULT 0,
                positions_count INTEGER DEFAULT 0,
                trades_opened INTEGER DEFAULT 0,
                trades_closed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS risk_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                message TEXT,
                severity TEXT DEFAULT 'info',
                trade_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
            CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
            CREATE INDEX IF NOT EXISTS idx_daily_pnl_date ON daily_pnl(date);
        """)


def insert_trade(trade: Dict) -> int:
    """Insert a new trade record."""
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO trades (
                trade_id, symbol, strategy, status,
                short_put_strike, long_put_strike, short_call_strike, long_call_strike,
                expiration, entry_credit, contracts, max_risk, max_profit,
                entry_time, entry_delta, entry_theta, entry_vega, entry_iv, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade['trade_id'], trade['symbol'], trade.get('strategy', 'iron_condor'),
            'open', trade['short_put_strike'], trade['long_put_strike'],
            trade['short_call_strike'], trade['long_call_strike'],
            trade['expiration'], trade['entry_credit'], trade.get('contracts', 1),
            trade['max_risk'], trade['max_profit'], trade['entry_time'],
            trade.get('entry_delta'), trade.get('entry_theta'),
            trade.get('entry_vega'), trade.get('entry_iv'), trade.get('notes')
        ))
        return cursor.lastrowid


def close_trade(trade_id: str, exit_debit: float, exit_reason: str, commissions: float = 0):
    """Close an existing trade and calculate P&L."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,)).fetchone()
        if not row:
            return None
        
        realized_pnl = (row['entry_credit'] - exit_debit) * row['contracts'] * 100 - commissions
        
        conn.execute("""
            UPDATE trades SET
                status = 'closed', exit_debit = ?, realized_pnl = ?,
                unrealized_pnl = 0, commissions = ?, exit_time = ?, exit_reason = ?
            WHERE trade_id = ?
        """, (exit_debit, realized_pnl, commissions, datetime.now().isoformat(), exit_reason, trade_id))
        
        return realized_pnl


def get_open_trades() -> List[Dict]:
    """Get all open trades."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM trades WHERE status = 'open' ORDER BY entry_time DESC").fetchall()
        return [dict(r) for r in rows]


def get_all_trades(limit: int = 100) -> List[Dict]:
    """Get recent trades."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_closed_trades(limit: int = 100) -> List[Dict]:
    """Get closed trades."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'closed' ORDER BY exit_time DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_daily_pnl(days: int = 30) -> List[Dict]:
    """Get daily P&L records."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_pnl ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
        return [dict(r) for r in rows]


def update_daily_pnl(pnl_data: Dict):
    """Insert or update daily P&L."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO daily_pnl (date, realized_pnl, unrealized_pnl, total_pnl,
                portfolio_value, positions_count, trades_opened, trades_closed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                realized_pnl = excluded.realized_pnl,
                unrealized_pnl = excluded.unrealized_pnl,
                total_pnl = excluded.total_pnl,
                portfolio_value = excluded.portfolio_value,
                positions_count = excluded.positions_count,
                trades_opened = excluded.trades_opened,
                trades_closed = excluded.trades_closed
        """, (
            pnl_data['date'], pnl_data['realized_pnl'], pnl_data['unrealized_pnl'],
            pnl_data['total_pnl'], pnl_data['portfolio_value'],
            pnl_data['positions_count'], pnl_data['trades_opened'], pnl_data['trades_closed']
        ))


def log_risk_event(event_type: str, message: str, severity: str = "info", trade_id: str = None):
    """Log a risk event."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO risk_events (event_type, message, severity, trade_id)
            VALUES (?, ?, ?, ?)
        """, (event_type, message, severity, trade_id))


def get_risk_events(limit: int = 50) -> List[Dict]:
    """Get recent risk events."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM risk_events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_today_stats() -> Dict:
    """Get today's trading statistics."""
    today = date.today().isoformat()
    with get_connection() as conn:
        opened = conn.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE date(entry_time) = ?", (today,)
        ).fetchone()['cnt']
        
        closed = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(realized_pnl), 0) as pnl FROM trades WHERE date(exit_time) = ?", (today,)
        ).fetchone()
        
        open_positions = conn.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE status = 'open'"
        ).fetchone()['cnt']
        
        return {
            'date': today,
            'trades_opened': opened,
            'trades_closed': closed['cnt'],
            'realized_pnl': closed['pnl'],
            'open_positions': open_positions
        }


def set_state(key: str, value: str):
    """Set a bot state value."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO bot_state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """, (key, value, datetime.now().isoformat()))


def get_state(key: str) -> Optional[str]:
    """Get a bot state value."""
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
        return row['value'] if row else None
