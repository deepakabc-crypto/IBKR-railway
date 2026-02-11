#!/usr/bin/env python3
"""
IBKR Iron Condor Trading Bot — Main Entry Point
Runs the trading loop alongside the monitoring dashboard.

Usage:
    python main.py              # Run bot + dashboard (default: paper trading)
    python main.py --live       # Run in live mode (requires IB_PORT=4001)
    python main.py --backtest   # Run backtest only
    python main.py --dashboard  # Run dashboard only (no trading)
"""
import os
import sys
import time
import signal
import argparse
import threading
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import strategy, risk, ENV, IB_HOST, IB_PORT
from utils.logger import log
from utils import database as db
from utils.ibkr_connection import IBKRConnection
from strategies.iron_condor import IronCondorStrategy
from dashboard.app import create_app


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(self, mode: str = "paper"):
        self.mode = mode
        self.running = False
        self.ibkr = None
        self.strategy = None
        
        # Initialize database
        db.init_db()
        log.info(f"🚀 Iron Condor Bot initializing | Mode: {mode.upper()}")

    def start(self):
        """Start the trading bot."""
        self.running = True
        db.set_state('bot_running', 'true')
        db.set_state('bot_mode', self.mode)
        db.set_state('bot_start_time', datetime.now().isoformat())
        
        # Connect to IBKR
        self.ibkr = IBKRConnection()
        if not self.ibkr.connect():
            log.error("❌ Cannot start bot — IBKR connection failed")
            log.error("   Make sure IB Gateway/TWS is running on "
                      f"{IB_HOST}:{IB_PORT}")
            db.set_state('bot_running', 'false')
            return False
        
        # Initialize strategy
        self.strategy = IronCondorStrategy(self.ibkr)
        
        log.info("=" * 60)
        log.info("  IRON CONDOR BOT — STARTED")
        log.info(f"  Mode:      {self.mode.upper()}")
        log.info(f"  Symbol:    {strategy.symbol}")
        log.info(f"  DTE:       {strategy.target_dte_min}-{strategy.target_dte_max}")
        log.info(f"  Deltas:    {strategy.short_put_delta}P / {strategy.short_call_delta}C")
        log.info(f"  Wings:     ${strategy.wing_width} wide")
        log.info(f"  Profit:    {strategy.profit_target_pct}% target")
        log.info(f"  Stop:      {strategy.stop_loss_pct}% loss")
        log.info(f"  Max Pos:   {strategy.max_positions}")
        log.info("=" * 60)
        
        # Main trading loop
        self._run_loop()
        return True

    def _run_loop(self):
        """Main trading loop."""
        while self.running:
            try:
                loop_start = datetime.now()
                db.set_state('last_check_time', loop_start.isoformat())
                
                # ── 1. Check exit conditions on open positions ────────
                exits = self.strategy.check_exit_signals()
                for trade, reason in exits:
                    log.info(f"🚪 Exit signal: {trade['trade_id']} — {reason}")
                    self.strategy.execute_exit(trade, reason)

                # ── 2. Check for new entry signal ─────────────────────
                signal = self.strategy.check_entry_signal()
                if signal:
                    log.info(f"🎯 Entry signal detected!")
                    self.strategy.execute_entry(signal)

                # ── 3. Update daily P&L ───────────────────────────────
                self._update_daily_pnl()

                # ── 4. Sleep until next check ─────────────────────────
                elapsed = (datetime.now() - loop_start).seconds
                sleep_time = max(1, strategy.check_interval_seconds - elapsed)
                
                log.debug(f"Next check in {sleep_time}s...")
                
                # Sleep in small increments so we can catch shutdown signals
                for _ in range(sleep_time):
                    if not self.running:
                        break
                    time.sleep(1)

            except KeyboardInterrupt:
                log.info("⚡ Keyboard interrupt received")
                self.stop()
                break
            except Exception as e:
                log.error(f"Error in main loop: {e}", exc_info=True)
                db.log_risk_event("bot_error", str(e), "error")
                time.sleep(10)

    def _update_daily_pnl(self):
        """Update the daily P&L record."""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            stats = db.get_today_stats()
            
            # Get account info if connected
            portfolio_value = 0
            if self.ibkr and self.ibkr.is_connected:
                try:
                    account = self.ibkr.get_account_summary()
                    portfolio_value = account.get('NetLiquidation', 0)
                except:
                    pass
            
            open_trades = db.get_open_trades()
            total_unrealized = sum(t.get('unrealized_pnl', 0) for t in open_trades)
            
            db.update_daily_pnl({
                'date': today,
                'realized_pnl': stats['realized_pnl'],
                'unrealized_pnl': total_unrealized,
                'total_pnl': stats['realized_pnl'] + total_unrealized,
                'portfolio_value': portfolio_value,
                'positions_count': stats['open_positions'],
                'trades_opened': stats['trades_opened'],
                'trades_closed': stats['trades_closed'],
            })
        except Exception as e:
            log.error(f"Error updating daily P&L: {e}")

    def stop(self):
        """Gracefully stop the bot."""
        log.info("🛑 Shutting down bot...")
        self.running = False
        db.set_state('bot_running', 'false')
        
        if self.ibkr:
            self.ibkr.disconnect()
        
        log.info("✅ Bot stopped")


def run_dashboard_only():
    """Run only the dashboard without trading."""
    db.init_db()
    app = create_app()
    log.info("🌐 Starting dashboard at http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)


def run_backtest_only():
    """Run backtest and print results."""
    from backtesting.engine import run_backtest
    log.info("🧪 Running backtest...")
    result = run_backtest()
    return result


def main():
    parser = argparse.ArgumentParser(description="IBKR Iron Condor Trading Bot")
    parser.add_argument('--live', action='store_true', help='Run in live trading mode')
    parser.add_argument('--backtest', action='store_true', help='Run backtest only')
    parser.add_argument('--dashboard', action='store_true', help='Run dashboard only')
    parser.add_argument('--port', type=int, default=5000, help='Dashboard port')
    args = parser.parse_args()

    if args.backtest:
        run_backtest_only()
        return

    if args.dashboard:
        run_dashboard_only()
        return

    # Full bot + dashboard mode
    mode = "live" if args.live else "paper"
    bot = TradingBot(mode=mode)

    # Handle shutdown signals
    def shutdown(signum, frame):
        bot.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start dashboard in background thread
    app = create_app()
    port = int(os.environ.get('PORT', args.port))
    dash_thread = threading.Thread(
        target=lambda: app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False),
        daemon=True
    )
    dash_thread.start()
    log.info(f"🌐 Dashboard running at http://0.0.0.0:{port}")

    # Start bot
    bot.start()


if __name__ == "__main__":
    main()
