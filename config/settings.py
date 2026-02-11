"""
IBKR Iron Condor Bot - Configuration Settings
Customize all parameters for your trading strategy, risk management, and deployment.
"""
import os
from dataclasses import dataclass, field
from typing import List

# ─── Environment Detection ────────────────────────────────────────────────────
ENV = os.getenv("BOT_ENV", "paper")  # "paper" or "live"
IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_PORT", "4002"))  # 4001=live, 4002=paper
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))


@dataclass
class StrategyConfig:
    """Iron Condor Strategy Parameters"""
    # ── Underlying ────────────────────────────────────────────────────────
    symbol: str = "SPY"
    exchange: str = "SMART"
    currency: str = "USD"

    # ── Iron Condor Construction ──────────────────────────────────────────
    # Delta targets for short strikes (higher = closer to ATM = more premium but riskier)
    short_put_delta: float = -0.16       # Short put delta target
    short_call_delta: float = 0.16       # Short call delta target
    wing_width: int = 5                  # Width of wings in strike $ (e.g., $5 wide)
    
    # ── DTE (Days to Expiration) ──────────────────────────────────────────
    target_dte_min: int = 30             # Minimum DTE for entry
    target_dte_max: int = 45             # Maximum DTE for entry
    
    # ── Entry Conditions ──────────────────────────────────────────────────
    min_credit: float = 0.80            # Minimum net credit to collect per spread ($)
    max_iv_rank: float = 80.0           # Maximum IV rank for entry (%)
    min_iv_rank: float = 20.0           # Minimum IV rank for entry (%)
    
    # ── Exit Conditions ───────────────────────────────────────────────────
    profit_target_pct: float = 50.0     # Close at 50% of max profit
    stop_loss_pct: float = 200.0        # Close at 2x premium received (200% loss)
    dte_exit: int = 7                   # Close if DTE <= this (avoid gamma risk)
    
    # ── Position Sizing ───────────────────────────────────────────────────
    max_positions: int = 3              # Max concurrent iron condors
    contracts_per_trade: int = 1        # Number of contracts per iron condor
    max_portfolio_risk_pct: float = 5.0 # Max % of portfolio at risk per trade
    max_total_risk_pct: float = 15.0    # Max total portfolio risk across all positions
    
    # ── Trading Schedule ──────────────────────────────────────────────────
    entry_days: List[str] = field(default_factory=lambda: ["Monday", "Tuesday", "Wednesday"])
    entry_time_start: str = "10:00"     # Don't enter before this time (ET)
    entry_time_end: str = "15:30"       # Don't enter after this time (ET)
    check_interval_seconds: int = 60    # How often to check positions/signals


@dataclass
class RiskConfig:
    """Risk Management Parameters"""
    # ── Daily Limits ──────────────────────────────────────────────────────
    max_daily_loss: float = 500.0       # Max loss per day before stopping ($)
    max_daily_trades: int = 3           # Max new trades per day
    
    # ── Weekly Limits ─────────────────────────────────────────────────────
    max_weekly_loss: float = 1500.0     # Max loss per week ($)
    
    # ── Drawdown Protection ───────────────────────────────────────────────
    max_drawdown_pct: float = 10.0      # Max portfolio drawdown before halting (%)
    drawdown_cooldown_hours: int = 24   # Hours to wait after max drawdown hit
    
    # ── Circuit Breakers ──────────────────────────────────────────────────
    consecutive_loss_limit: int = 3     # Halt after N consecutive losing trades
    vix_max_entry: float = 35.0         # Don't enter if VIX > this
    vix_min_entry: float = 12.0         # Don't enter if VIX < this (premiums too low)


@dataclass
class BacktestConfig:
    """Backtesting Parameters"""
    start_date: str = "2023-01-01"
    end_date: str = "2025-01-01"
    initial_capital: float = 50000.0
    commission_per_contract: float = 0.65
    slippage_pct: float = 2.0           # % slippage on fills
    data_source: str = "yahoo"          # "yahoo" or "ibkr"


@dataclass
class DashboardConfig:
    """Dashboard Settings"""
    host: str = "0.0.0.0"
    port: int = 5000
    secret_key: str = os.getenv("DASHBOARD_SECRET", "change-me-in-production")
    refresh_interval: int = 30          # Dashboard auto-refresh interval (seconds)
    log_file: str = "logs/trading.log"
    db_file: str = "data/trades.db"


# ─── Instantiate Configs ──────────────────────────────────────────────────────
strategy = StrategyConfig()
risk = RiskConfig()
backtest = BacktestConfig()
dashboard = DashboardConfig()
