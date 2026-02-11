"""
Iron Condor Bot Dashboard
Real-time monitoring dashboard with P&L tracking, position management, and backtest results.
"""
import json
import os
from datetime import datetime, date
from dataclasses import asdict

from flask import Flask, render_template, jsonify, request, redirect, url_for

from config import strategy, risk, backtest, dashboard as dash_config, ENV
from utils import database as db
from utils.logger import log

app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
            static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'))
app.secret_key = dash_config.secret_key


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('dashboard.html',
                         env=ENV,
                         strategy_config=strategy,
                         risk_config=risk)


@app.route('/api/status')
def api_status():
    """Bot status and summary."""
    try:
        today_stats = db.get_today_stats()
        open_trades = db.get_open_trades()
        
        # Calculate total unrealized
        total_unrealized = sum(t.get('unrealized_pnl', 0) for t in open_trades)
        
        # Get bot state
        bot_running = db.get_state('bot_running') == 'true'
        last_check = db.get_state('last_check_time')
        
        return jsonify({
            'status': 'running' if bot_running else 'stopped',
            'environment': ENV,
            'last_check': last_check,
            'today': today_stats,
            'open_positions': len(open_trades),
            'total_unrealized': round(total_unrealized, 2),
            'timestamp': datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/positions')
def api_positions():
    """Current open positions."""
    try:
        trades = db.get_open_trades()
        return jsonify({'positions': trades})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/trades')
def api_trades():
    """Recent trade history."""
    try:
        limit = request.args.get('limit', 50, type=int)
        trades = db.get_all_trades(limit=limit)
        return jsonify({'trades': trades})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/pnl')
def api_pnl():
    """Daily P&L data."""
    try:
        days = request.args.get('days', 30, type=int)
        pnl_data = db.get_daily_pnl(days=days)
        return jsonify({'daily_pnl': pnl_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/risk-events')
def api_risk_events():
    """Recent risk events."""
    try:
        events = db.get_risk_events(limit=30)
        return jsonify({'events': events})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/equity-curve')
def api_equity_curve():
    """Get equity curve data (from backtest results or live tracking)."""
    try:
        pnl_data = db.get_daily_pnl(days=365)
        
        if not pnl_data:
            return jsonify({'equity_curve': []})
        
        curve = []
        for d in reversed(pnl_data):
            curve.append({
                'date': d['date'],
                'equity': d['portfolio_value'],
                'pnl': d['total_pnl']
            })
        
        return jsonify({'equity_curve': curve})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/backtest', methods=['POST'])
def api_run_backtest():
    """Run a backtest with custom parameters."""
    try:
        from backtesting.engine import BacktestEngine
        
        data = request.get_json() or {}
        engine = BacktestEngine()
        result = engine.run(
            start_date=data.get('start_date', backtest.start_date),
            end_date=data.get('end_date', backtest.end_date),
            initial_capital=data.get('initial_capital', backtest.initial_capital)
        )
        
        return jsonify({
            'total_trades': result.total_trades,
            'win_rate': result.win_rate,
            'total_pnl': result.total_pnl,
            'total_return_pct': result.total_return_pct,
            'annualized_return_pct': result.annualized_return_pct,
            'max_drawdown_pct': result.max_drawdown_pct,
            'sharpe_ratio': result.sharpe_ratio,
            'sortino_ratio': result.sortino_ratio,
            'profit_factor': result.profit_factor,
            'avg_win': result.avg_win,
            'avg_loss': result.avg_loss,
            'largest_win': result.largest_win,
            'largest_loss': result.largest_loss,
            'equity_curve': result.equity_curve,
            'monthly_returns': result.monthly_returns,
            'trades': result.trades[:100],  # Limit for API response
        })
    except Exception as e:
        log.error(f"Backtest error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/config')
def api_config():
    """Current bot configuration."""
    return jsonify({
        'strategy': {
            'symbol': strategy.symbol,
            'short_put_delta': strategy.short_put_delta,
            'short_call_delta': strategy.short_call_delta,
            'wing_width': strategy.wing_width,
            'target_dte_min': strategy.target_dte_min,
            'target_dte_max': strategy.target_dte_max,
            'min_credit': strategy.min_credit,
            'profit_target_pct': strategy.profit_target_pct,
            'stop_loss_pct': strategy.stop_loss_pct,
            'dte_exit': strategy.dte_exit,
            'max_positions': strategy.max_positions,
            'contracts_per_trade': strategy.contracts_per_trade,
        },
        'risk': {
            'max_daily_loss': risk.max_daily_loss,
            'max_daily_trades': risk.max_daily_trades,
            'max_drawdown_pct': risk.max_drawdown_pct,
            'consecutive_loss_limit': risk.consecutive_loss_limit,
            'vix_max_entry': risk.vix_max_entry,
        },
        'environment': ENV,
    })


def create_app():
    """Application factory."""
    db.init_db()
    return app


if __name__ == '__main__':
    application = create_app()
    port = int(os.environ.get('PORT', dash_config.port))
    application.run(host=dash_config.host, port=port, debug=True)
