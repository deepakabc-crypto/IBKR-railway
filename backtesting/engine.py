"""
Iron Condor Backtesting Engine
Simulates historical performance using SPY price data with realistic modeling
of options pricing, slippage, and commissions.
"""
import json
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

import numpy as np

from config import strategy, risk, backtest
from utils.logger import log


@dataclass
class BacktestTrade:
    """Represents a single backtested iron condor trade."""
    trade_id: str = ""
    entry_date: str = ""
    exit_date: str = ""
    expiration: str = ""
    dte_at_entry: int = 0
    spy_price_entry: float = 0
    spy_price_exit: float = 0
    short_put: float = 0
    long_put: float = 0
    short_call: float = 0
    long_call: float = 0
    entry_credit: float = 0
    exit_debit: float = 0
    contracts: int = 1
    pnl: float = 0
    pnl_pct: float = 0
    max_risk: float = 0
    exit_reason: str = ""
    iv_at_entry: float = 0
    win: bool = False


@dataclass
class BacktestResult:
    """Complete backtest results and statistics."""
    # Settings
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 0
    
    # Summary Stats
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0
    
    # P&L
    total_pnl: float = 0
    avg_pnl: float = 0
    avg_win: float = 0
    avg_loss: float = 0
    largest_win: float = 0
    largest_loss: float = 0
    profit_factor: float = 0
    
    # Risk
    max_drawdown: float = 0
    max_drawdown_pct: float = 0
    sharpe_ratio: float = 0
    sortino_ratio: float = 0
    calmar_ratio: float = 0
    
    # Returns
    total_return_pct: float = 0
    annualized_return_pct: float = 0
    final_capital: float = 0
    
    # Equity curve
    equity_curve: List[Dict] = field(default_factory=list)
    monthly_returns: List[Dict] = field(default_factory=list)
    trades: List[Dict] = field(default_factory=list)


class OptionsSimulator:
    """Simplified Black-Scholes based options pricing for backtesting."""

    @staticmethod
    def estimate_iv(spy_price: float, date: datetime) -> float:
        """Estimate implied volatility based on historical VIX patterns."""
        # Simplified: use a base IV with seasonal adjustments
        base_iv = 0.18  # ~18% base IV for SPY
        
        month = date.month
        # Higher IV in Sept-Oct, lower in summer
        seasonal = {1: 1.0, 2: 1.05, 3: 1.1, 4: 0.95, 5: 0.9, 6: 0.85,
                    7: 0.85, 8: 0.95, 9: 1.15, 10: 1.2, 11: 1.0, 12: 0.95}
        
        return base_iv * seasonal.get(month, 1.0)

    @staticmethod
    def black_scholes_price(S: float, K: float, T: float, r: float, sigma: float, 
                            option_type: str = 'call') -> float:
        """Calculate Black-Scholes option price."""
        if T <= 0:
            if option_type == 'call':
                return max(S - K, 0)
            else:
                return max(K - S, 0)
        
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        
        from scipy.stats import norm
        
        if option_type == 'call':
            price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
        else:
            price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        
        return max(price, 0)

    @staticmethod
    def bs_delta(S: float, K: float, T: float, r: float, sigma: float,
                 option_type: str = 'call') -> float:
        """Calculate option delta."""
        if T <= 0:
            if option_type == 'call':
                return 1.0 if S > K else 0.0
            else:
                return -1.0 if S < K else 0.0
        
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        from scipy.stats import norm
        
        if option_type == 'call':
            return norm.cdf(d1)
        else:
            return norm.cdf(d1) - 1

    @classmethod
    def find_strike_for_delta(cls, S: float, target_delta: float, T: float, r: float,
                              sigma: float, option_type: str, strikes: List[float]) -> float:
        """Find the closest strike to target delta."""
        best_strike = None
        best_diff = float('inf')
        
        for K in strikes:
            delta = cls.bs_delta(S, K, T, r, sigma, option_type)
            diff = abs(abs(delta) - abs(target_delta))
            if diff < best_diff:
                best_diff = diff
                best_strike = K
        
        return best_strike


class BacktestEngine:
    """
    Main backtesting engine for Iron Condor strategy.
    
    Uses historical SPY price data and simulated options pricing to evaluate
    strategy performance over a historical period.
    """

    def __init__(self, config: Dict = None):
        self.initial_capital = backtest.initial_capital
        self.commission = backtest.commission_per_contract
        self.slippage_pct = backtest.slippage_pct / 100
        self.sim = OptionsSimulator()
        self.risk_free_rate = 0.05  # 5% risk-free rate

    def load_spy_data(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """Load SPY historical price data from Yahoo Finance."""
        import yfinance as yf
        
        start = start_date or backtest.start_date
        end = end_date or backtest.end_date
        
        log.info(f"Loading SPY data from {start} to {end}...")
        spy = yf.download("SPY", start=start, end=end, auto_adjust=True)
        
        data = []
        for date_idx, row in spy.iterrows():
            dt = date_idx
            if hasattr(dt, 'to_pydatetime'):
                dt = dt.to_pydatetime()
            data.append({
                'date': dt,
                'open': float(row.iloc[0]) if hasattr(row.iloc[0], 'item') else float(row.iloc[0]),
                'high': float(row.iloc[1]) if hasattr(row.iloc[1], 'item') else float(row.iloc[1]),
                'low': float(row.iloc[2]) if hasattr(row.iloc[2], 'item') else float(row.iloc[2]),
                'close': float(row.iloc[3]) if hasattr(row.iloc[3], 'item') else float(row.iloc[3]),
                'volume': float(row.iloc[4]) if hasattr(row.iloc[4], 'item') else float(row.iloc[4]),
            })
        
        log.info(f"Loaded {len(data)} trading days")
        return data

    def generate_strikes(self, spy_price: float) -> List[float]:
        """Generate realistic strike prices around current price."""
        base = round(spy_price)
        return [base + i for i in range(-50, 51)]

    def run(self, start_date: str = None, end_date: str = None,
            initial_capital: float = None) -> BacktestResult:
        """Run the full backtest simulation."""
        capital = initial_capital or self.initial_capital
        
        # Load data
        price_data = self.load_spy_data(start_date, end_date)
        if not price_data:
            log.error("No price data loaded")
            return BacktestResult()

        result = BacktestResult(
            start_date=start_date or backtest.start_date,
            end_date=end_date or backtest.end_date,
            initial_capital=capital,
        )

        # State tracking
        equity = capital
        peak_equity = capital
        max_drawdown = 0
        open_positions: List[BacktestTrade] = []
        closed_trades: List[BacktestTrade] = []
        equity_curve = []
        daily_returns = []
        prev_equity = capital
        trade_counter = 0
        
        # Weekly entry tracking
        last_entry_week = None

        for i, day in enumerate(price_data):
            date = day['date']
            price = day['close']
            high = day['high']
            low = day['low']
            
            # ── Check Exits ───────────────────────────────────────────────
            positions_to_close = []
            for pos in open_positions:
                exit_reason = self._check_exit_conditions(pos, date, price, high, low)
                if exit_reason:
                    positions_to_close.append((pos, exit_reason))
            
            for pos, reason in positions_to_close:
                pos = self._close_position(pos, date, price, reason)
                equity += pos.pnl
                closed_trades.append(pos)
                open_positions.remove(pos)

            # ── Check Entry ───────────────────────────────────────────────
            day_name = date.strftime("%A")
            current_week = date.isocalendar()[1]
            
            can_enter = (
                day_name in strategy.entry_days
                and len(open_positions) < strategy.max_positions
                and current_week != last_entry_week  # Max one entry per week
            )
            
            if can_enter:
                new_trade = self._try_open_position(date, price, trade_counter, equity)
                if new_trade:
                    open_positions.append(new_trade)
                    trade_counter += 1
                    last_entry_week = current_week

            # ── Update Equity Curve ───────────────────────────────────────
            unrealized = sum(
                self._calc_unrealized(pos, date, price) for pos in open_positions
            )
            current_equity = equity + unrealized
            
            # Track drawdown
            if current_equity > peak_equity:
                peak_equity = current_equity
            dd = (peak_equity - current_equity) / peak_equity * 100
            if dd > max_drawdown:
                max_drawdown = dd

            # Daily return
            daily_ret = (current_equity - prev_equity) / prev_equity if prev_equity > 0 else 0
            daily_returns.append(daily_ret)
            prev_equity = current_equity

            equity_curve.append({
                'date': date.strftime('%Y-%m-%d'),
                'equity': round(current_equity, 2),
                'drawdown': round(dd, 2),
                'open_positions': len(open_positions),
            })

        # ── Close remaining positions at end ──────────────────────────────
        final_date = price_data[-1]['date']
        final_price = price_data[-1]['close']
        for pos in open_positions:
            pos = self._close_position(pos, final_date, final_price, "backtest_end")
            equity += pos.pnl
            closed_trades.append(pos)

        # ── Calculate Statistics ──────────────────────────────────────────
        result = self._calculate_stats(result, closed_trades, equity_curve, 
                                        daily_returns, equity, max_drawdown)
        
        return result

    def _try_open_position(self, date: datetime, spy_price: float, 
                           counter: int, current_equity: float) -> Optional[BacktestTrade]:
        """Try to open a new iron condor position."""
        strikes = self.generate_strikes(spy_price)
        iv = self.sim.estimate_iv(spy_price, date)
        
        # Target expiration ~35 DTE
        target_dte = (strategy.target_dte_min + strategy.target_dte_max) // 2
        T = target_dte / 365.0
        
        # Find short strikes by delta
        short_put = self.sim.find_strike_for_delta(
            spy_price, abs(strategy.short_put_delta), T, self.risk_free_rate, iv, 'put', strikes
        )
        short_call = self.sim.find_strike_for_delta(
            spy_price, abs(strategy.short_call_delta), T, self.risk_free_rate, iv, 'call', strikes
        )
        
        if not short_put or not short_call:
            return None
        
        long_put = short_put - strategy.wing_width
        long_call = short_call + strategy.wing_width
        
        # Calculate premiums
        sp_price = self.sim.black_scholes_price(spy_price, short_put, T, self.risk_free_rate, iv, 'put')
        lp_price = self.sim.black_scholes_price(spy_price, long_put, T, self.risk_free_rate, iv, 'put')
        sc_price = self.sim.black_scholes_price(spy_price, short_call, T, self.risk_free_rate, iv, 'call')
        lc_price = self.sim.black_scholes_price(spy_price, long_call, T, self.risk_free_rate, iv, 'call')
        
        credit = (sp_price + sc_price) - (lp_price + lc_price)
        
        # Apply slippage
        credit *= (1 - self.slippage_pct)
        
        if credit < strategy.min_credit:
            return None
        
        max_risk = (strategy.wing_width - credit) * 100
        
        # Position size check
        risk_pct = max_risk / current_equity * 100
        if risk_pct > strategy.max_portfolio_risk_pct:
            return None
        
        expiration_date = date + timedelta(days=target_dte)
        
        trade = BacktestTrade(
            trade_id=f"BT_{counter:04d}",
            entry_date=date.strftime('%Y-%m-%d'),
            expiration=expiration_date.strftime('%Y-%m-%d'),
            dte_at_entry=target_dte,
            spy_price_entry=round(spy_price, 2),
            short_put=short_put,
            long_put=long_put,
            short_call=short_call,
            long_call=long_call,
            entry_credit=round(credit, 2),
            max_risk=round(max_risk, 2),
            contracts=strategy.contracts_per_trade,
            iv_at_entry=round(iv, 4),
        )
        
        return trade

    def _check_exit_conditions(self, trade: BacktestTrade, date: datetime,
                                price: float, high: float, low: float) -> Optional[str]:
        """Check if any exit condition is met."""
        exp_date = datetime.strptime(trade.expiration, '%Y-%m-%d')
        dte = (exp_date - date).days
        
        # DTE exit
        if dte <= strategy.dte_exit:
            return "dte_exit"
        
        # Expiration
        if date >= exp_date:
            return "expiration"
        
        # Calculate current spread value
        T = max(dte / 365.0, 0.001)
        iv = self.sim.estimate_iv(price, date) * 1.05  # Slight IV expansion in exit
        
        sp = self.sim.black_scholes_price(price, trade.short_put, T, self.risk_free_rate, iv, 'put')
        lp = self.sim.black_scholes_price(price, trade.long_put, T, self.risk_free_rate, iv, 'put')
        sc = self.sim.black_scholes_price(price, trade.short_call, T, self.risk_free_rate, iv, 'call')
        lc = self.sim.black_scholes_price(price, trade.long_call, T, self.risk_free_rate, iv, 'call')
        
        current_value = (sp + sc) - (lp + lc)
        
        # Profit target
        profit_pct = ((trade.entry_credit - current_value) / trade.entry_credit) * 100
        if profit_pct >= strategy.profit_target_pct:
            return "profit_target"
        
        # Stop loss
        loss_pct = ((current_value - trade.entry_credit) / trade.entry_credit) * 100
        if loss_pct >= strategy.stop_loss_pct:
            return "stop_loss"
        
        # Test if price breached short strikes significantly (intraday)
        if low <= trade.long_put or high >= trade.long_call:
            return "wing_breach"
        
        return None

    def _close_position(self, trade: BacktestTrade, date: datetime,
                        price: float, reason: str) -> BacktestTrade:
        """Close a position and calculate P&L."""
        exp_date = datetime.strptime(trade.expiration, '%Y-%m-%d')
        dte = max((exp_date - date).days, 0)
        T = max(dte / 365.0, 0.001)
        iv = self.sim.estimate_iv(price, date)
        
        if reason == "expiration" or dte <= 0:
            # At expiration, calculate intrinsic value
            sp_val = max(trade.short_put - price, 0)
            lp_val = max(trade.long_put - price, 0)
            sc_val = max(price - trade.short_call, 0)
            lc_val = max(price - trade.long_call, 0)
        else:
            sp_val = self.sim.black_scholes_price(price, trade.short_put, T, self.risk_free_rate, iv, 'put')
            lp_val = self.sim.black_scholes_price(price, trade.long_put, T, self.risk_free_rate, iv, 'put')
            sc_val = self.sim.black_scholes_price(price, trade.short_call, T, self.risk_free_rate, iv, 'call')
            lc_val = self.sim.black_scholes_price(price, trade.long_call, T, self.risk_free_rate, iv, 'call')
        
        exit_debit = (sp_val + sc_val) - (lp_val + lc_val)
        exit_debit *= (1 + self.slippage_pct)  # Slippage on exit
        
        commissions = 4 * self.commission * 2 * trade.contracts  # 4 legs, entry + exit
        pnl = (trade.entry_credit - exit_debit) * trade.contracts * 100 - commissions
        
        trade.exit_date = date.strftime('%Y-%m-%d')
        trade.spy_price_exit = round(price, 2)
        trade.exit_debit = round(exit_debit, 2)
        trade.pnl = round(pnl, 2)
        trade.pnl_pct = round(pnl / trade.max_risk * 100, 2) if trade.max_risk > 0 else 0
        trade.exit_reason = reason
        trade.win = pnl > 0
        
        return trade

    def _calc_unrealized(self, trade: BacktestTrade, date: datetime, price: float) -> float:
        """Calculate unrealized P&L for an open position."""
        exp_date = datetime.strptime(trade.expiration, '%Y-%m-%d')
        dte = max((exp_date - date).days, 0)
        T = max(dte / 365.0, 0.001)
        iv = self.sim.estimate_iv(price, date)
        
        sp = self.sim.black_scholes_price(price, trade.short_put, T, self.risk_free_rate, iv, 'put')
        lp = self.sim.black_scholes_price(price, trade.long_put, T, self.risk_free_rate, iv, 'put')
        sc = self.sim.black_scholes_price(price, trade.short_call, T, self.risk_free_rate, iv, 'call')
        lc = self.sim.black_scholes_price(price, trade.long_call, T, self.risk_free_rate, iv, 'call')
        
        current_value = (sp + sc) - (lp + lc)
        return (trade.entry_credit - current_value) * trade.contracts * 100

    def _calculate_stats(self, result: BacktestResult, trades: List[BacktestTrade],
                         equity_curve: List, daily_returns: List, 
                         final_equity: float, max_dd: float) -> BacktestResult:
        """Calculate comprehensive backtest statistics."""
        if not trades:
            return result
        
        pnls = [t.pnl for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        result.total_trades = len(trades)
        result.winning_trades = len(wins)
        result.losing_trades = len(losses)
        result.win_rate = len(wins) / len(trades) * 100 if trades else 0
        
        result.total_pnl = round(sum(pnls), 2)
        result.avg_pnl = round(np.mean(pnls), 2) if pnls else 0
        result.avg_win = round(np.mean(wins), 2) if wins else 0
        result.avg_loss = round(np.mean(losses), 2) if losses else 0
        result.largest_win = round(max(pnls), 2) if pnls else 0
        result.largest_loss = round(min(pnls), 2) if pnls else 0
        
        total_wins = sum(wins) if wins else 0
        total_losses = abs(sum(losses)) if losses else 1
        result.profit_factor = round(total_wins / total_losses, 2) if total_losses > 0 else float('inf')
        
        result.max_drawdown = round(max_dd, 2)
        result.max_drawdown_pct = round(max_dd, 2)
        
        result.final_capital = round(final_equity, 2)
        result.total_return_pct = round((final_equity - result.initial_capital) / result.initial_capital * 100, 2)
        
        # Annualized return
        if equity_curve and len(equity_curve) > 1:
            days = len(equity_curve)
            years = days / 252
            if years > 0:
                result.annualized_return_pct = round(
                    ((final_equity / result.initial_capital) ** (1 / years) - 1) * 100, 2
                )
        
        # Sharpe Ratio (annualized)
        if daily_returns and len(daily_returns) > 1:
            dr = np.array(daily_returns)
            if np.std(dr) > 0:
                result.sharpe_ratio = round(np.mean(dr) / np.std(dr) * math.sqrt(252), 2)
            
            # Sortino Ratio
            downside = dr[dr < 0]
            if len(downside) > 0 and np.std(downside) > 0:
                result.sortino_ratio = round(np.mean(dr) / np.std(downside) * math.sqrt(252), 2)
        
        # Calmar Ratio
        if max_dd > 0 and result.annualized_return_pct:
            result.calmar_ratio = round(result.annualized_return_pct / max_dd, 2)
        
        result.equity_curve = equity_curve
        result.trades = [asdict(t) for t in trades]
        
        # Monthly returns
        monthly = {}
        for t in trades:
            month = t.exit_date[:7] if t.exit_date else t.entry_date[:7]
            monthly.setdefault(month, 0)
            monthly[month] += t.pnl
        result.monthly_returns = [{'month': k, 'pnl': round(v, 2)} for k, v in sorted(monthly.items())]
        
        return result

    def print_report(self, result: BacktestResult):
        """Print a formatted backtest report to console."""
        print("\n" + "=" * 70)
        print("           IRON CONDOR BACKTEST REPORT")
        print("=" * 70)
        print(f"  Period:          {result.start_date} → {result.end_date}")
        print(f"  Initial Capital: ${result.initial_capital:,.2f}")
        print(f"  Final Capital:   ${result.final_capital:,.2f}")
        print("-" * 70)
        print(f"  Total Trades:    {result.total_trades}")
        print(f"  Win Rate:        {result.win_rate:.1f}%")
        print(f"  Profit Factor:   {result.profit_factor:.2f}")
        print("-" * 70)
        print(f"  Total P&L:       ${result.total_pnl:,.2f}")
        print(f"  Avg Trade P&L:   ${result.avg_pnl:,.2f}")
        print(f"  Avg Win:         ${result.avg_win:,.2f}")
        print(f"  Avg Loss:        ${result.avg_loss:,.2f}")
        print(f"  Largest Win:     ${result.largest_win:,.2f}")
        print(f"  Largest Loss:    ${result.largest_loss:,.2f}")
        print("-" * 70)
        print(f"  Total Return:    {result.total_return_pct:.2f}%")
        print(f"  Annual Return:   {result.annualized_return_pct:.2f}%")
        print(f"  Max Drawdown:    {result.max_drawdown_pct:.2f}%")
        print(f"  Sharpe Ratio:    {result.sharpe_ratio:.2f}")
        print(f"  Sortino Ratio:   {result.sortino_ratio:.2f}")
        print(f"  Calmar Ratio:    {result.calmar_ratio:.2f}")
        print("=" * 70)
        
        print("\n  Exit Reasons:")
        reasons = {}
        for t in result.trades:
            r = t.get('exit_reason', 'unknown')
            reasons[r] = reasons.get(r, 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason:20s}: {count:3d} ({count/result.total_trades*100:.1f}%)")
        
        print("\n  Monthly P&L:")
        for m in result.monthly_returns:
            bar = "█" * max(1, int(abs(m['pnl']) / 50))
            sign = "+" if m['pnl'] > 0 else ""
            print(f"    {m['month']}: {sign}${m['pnl']:>8,.2f}  {'🟢' if m['pnl'] > 0 else '🔴'} {bar}")
        
        print("=" * 70)


def run_backtest(start: str = None, end: str = None, capital: float = None) -> BacktestResult:
    """Convenience function to run a backtest."""
    engine = BacktestEngine()
    result = engine.run(start_date=start, end_date=end, initial_capital=capital)
    engine.print_report(result)
    return result


if __name__ == "__main__":
    result = run_backtest()
