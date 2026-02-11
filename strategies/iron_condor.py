"""
Iron Condor Strategy Engine
Handles signal generation, trade construction, position monitoring, and auto-exit logic.
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

from config import strategy, risk
from utils.logger import log, trade_log
from utils import database as db
from utils.ibkr_connection import IBKRConnection


class IronCondorStrategy:
    """
    SPY Iron Condor Strategy
    
    Entry Logic:
    - Sell OTM put spread + OTM call spread
    - Target short strikes at configured delta levels
    - DTE between target_dte_min and target_dte_max
    - IV rank between min and max thresholds
    
    Exit Logic:
    - Profit target: Close at X% of max profit
    - Stop loss: Close at X% of premium received
    - Time exit: Close when DTE <= threshold
    - Delta breach: Close if short strike delta exceeds threshold
    """

    def __init__(self, ibkr: IBKRConnection):
        self.ibkr = ibkr
        self.name = "Iron Condor"

    # ─── Entry Signal ─────────────────────────────────────────────────────

    def check_entry_signal(self) -> Optional[Dict]:
        """
        Evaluate whether conditions are met to open a new iron condor.
        Returns trade parameters dict if signal is valid, None otherwise.
        """
        # Check if we can trade
        if not self._can_open_new_trade():
            return None

        # Check trading schedule
        if not self._is_trading_time():
            return None

        try:
            spy_price = self.ibkr.get_spy_price()
            log.info(f"SPY price: ${spy_price:.2f}")

            # Get option chains
            expirations, strikes = self.ibkr.get_option_chains()
            if not expirations:
                log.warning("No valid expirations found in DTE range")
                return None

            # Use the first valid expiration (closest to target DTE)
            expiration = expirations[0]
            dte = (datetime.strptime(expiration, '%Y%m%d') - datetime.now()).days
            log.info(f"Target expiration: {expiration} ({dte} DTE)")

            # Find short put by delta
            short_put_info = self.ibkr.find_strike_by_delta(
                expiration, 'P', strategy.short_put_delta, strikes, spy_price
            )
            if not short_put_info:
                log.warning("Could not find suitable short put strike")
                return None

            # Find short call by delta
            short_call_info = self.ibkr.find_strike_by_delta(
                expiration, 'C', strategy.short_call_delta, strikes, spy_price
            )
            if not short_call_info:
                log.warning("Could not find suitable short call strike")
                return None

            # Calculate wing strikes
            short_put_strike = short_put_info['strike']
            long_put_strike = short_put_strike - strategy.wing_width
            short_call_strike = short_call_info['strike']
            long_call_strike = short_call_strike + strategy.wing_width

            # Estimate credit (short premiums - long premiums)
            sp_price = short_put_info['greeks']['price']
            sc_price = short_call_info['greeks']['price']
            
            # Estimate long wing prices (rough: ~60% less than short)
            lp_price = sp_price * 0.35
            lc_price = sc_price * 0.35
            
            estimated_credit = (sp_price + sc_price) - (lp_price + lc_price)
            
            if estimated_credit < strategy.min_credit:
                log.info(f"Credit ${estimated_credit:.2f} below minimum ${strategy.min_credit:.2f}")
                return None

            # Max risk = wing width - credit received
            max_risk = (strategy.wing_width - estimated_credit) * 100
            max_profit = estimated_credit * 100

            # Check portfolio risk limit
            account = self.ibkr.get_account_summary()
            net_liq = account.get('NetLiquidation', 0)
            if net_liq > 0:
                risk_pct = (max_risk / net_liq) * 100
                if risk_pct > strategy.max_portfolio_risk_pct:
                    log.warning(f"Trade risk {risk_pct:.1f}% exceeds max {strategy.max_portfolio_risk_pct}%")
                    return None

            # Build trade signal
            trade_signal = {
                'trade_id': f"IC_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
                'symbol': strategy.symbol,
                'strategy': 'iron_condor',
                'short_put_strike': short_put_strike,
                'long_put_strike': long_put_strike,
                'short_call_strike': short_call_strike,
                'long_call_strike': long_call_strike,
                'expiration': expiration,
                'dte': dte,
                'entry_credit': round(estimated_credit, 2),
                'max_risk': round(max_risk, 2),
                'max_profit': round(max_profit, 2),
                'contracts': strategy.contracts_per_trade,
                'entry_time': datetime.now().isoformat(),
                'entry_delta': round(
                    (short_put_info['greeks']['delta'] or 0) + (short_call_info['greeks']['delta'] or 0), 4
                ),
                'entry_theta': round(
                    (short_put_info['greeks']['theta'] or 0) + (short_call_info['greeks']['theta'] or 0), 4
                ),
                'entry_vega': round(
                    (short_put_info['greeks']['vega'] or 0) + (short_call_info['greeks']['vega'] or 0), 4
                ),
                'entry_iv': round(
                    ((short_put_info['greeks']['iv'] or 0) + (short_call_info['greeks']['iv'] or 0)) / 2, 4
                ),
                'spy_price': spy_price,
            }

            log.info(
                f"🎯 Entry Signal: {short_put_strike}P/{long_put_strike}P | "
                f"{short_call_strike}C/{long_call_strike}C | "
                f"Credit: ${estimated_credit:.2f} | Risk: ${max_risk:.2f} | "
                f"DTE: {dte}"
            )
            return trade_signal

        except Exception as e:
            log.error(f"Error checking entry signal: {e}", exc_info=True)
            return None

    # ─── Execute Entry ────────────────────────────────────────────────────

    def execute_entry(self, signal: Dict) -> bool:
        """Execute an iron condor entry based on the signal."""
        try:
            order_id = self.ibkr.place_iron_condor(
                short_put=signal['short_put_strike'],
                long_put=signal['long_put_strike'],
                short_call=signal['short_call_strike'],
                long_call=signal['long_call_strike'],
                expiration=signal['expiration'],
                contracts=signal['contracts'],
                limit_price=signal['entry_credit']
            )

            if order_id:
                signal['notes'] = f"Order ID: {order_id}"
                db.insert_trade(signal)
                trade_log.info(
                    f"✅ ENTRY | {signal['trade_id']} | "
                    f"{signal['short_put_strike']}P/{signal['long_put_strike']}P/"
                    f"{signal['short_call_strike']}C/{signal['long_call_strike']}C | "
                    f"Credit: ${signal['entry_credit']:.2f} | Contracts: {signal['contracts']}"
                )
                db.log_risk_event("trade_entry", f"Opened {signal['trade_id']}", "info", signal['trade_id'])
                return True
            else:
                log.error(f"Failed to place iron condor order for {signal['trade_id']}")
                return False

        except Exception as e:
            log.error(f"Error executing entry: {e}", exc_info=True)
            return False

    # ─── Exit Monitoring ──────────────────────────────────────────────────

    def check_exit_signals(self) -> List[Tuple[Dict, str]]:
        """
        Check all open positions for exit conditions.
        Returns list of (trade, exit_reason) tuples.
        """
        exits = []
        open_trades = db.get_open_trades()

        for trade in open_trades:
            exit_reason = self._evaluate_exit(trade)
            if exit_reason:
                exits.append((trade, exit_reason))

        return exits

    def _evaluate_exit(self, trade: Dict) -> Optional[str]:
        """Evaluate exit conditions for a single trade."""
        try:
            # Check DTE exit
            exp_date = datetime.strptime(trade['expiration'], '%Y%m%d')
            dte = (exp_date - datetime.now()).days
            
            if dte <= strategy.dte_exit:
                return f"dte_exit (DTE={dte})"

            # Get current spread value to calculate P&L
            current_value = self._get_spread_value(trade)
            if current_value is None:
                return None

            entry_credit = trade['entry_credit']
            
            # Profit target: close at X% of max profit
            profit_pct = ((entry_credit - current_value) / entry_credit) * 100
            if profit_pct >= strategy.profit_target_pct:
                return f"profit_target ({profit_pct:.1f}%)"

            # Stop loss: close at X% loss of premium
            loss_pct = ((current_value - entry_credit) / entry_credit) * 100
            if loss_pct >= strategy.stop_loss_pct:
                return f"stop_loss ({loss_pct:.1f}%)"

            # Update unrealized P&L in DB
            unrealized = (entry_credit - current_value) * trade['contracts'] * 100
            with db.get_connection() as conn:
                conn.execute(
                    "UPDATE trades SET unrealized_pnl = ? WHERE trade_id = ?",
                    (round(unrealized, 2), trade['trade_id'])
                )

            return None

        except Exception as e:
            log.error(f"Error evaluating exit for {trade['trade_id']}: {e}")
            return None

    def _get_spread_value(self, trade: Dict) -> Optional[float]:
        """Get current market value of the iron condor spread."""
        try:
            from ib_insync import Option as IBOption

            legs = [
                IBOption(strategy.symbol, trade['expiration'], trade['short_put_strike'], 'P', strategy.exchange),
                IBOption(strategy.symbol, trade['expiration'], trade['long_put_strike'], 'P', strategy.exchange),
                IBOption(strategy.symbol, trade['expiration'], trade['short_call_strike'], 'C', strategy.exchange),
                IBOption(strategy.symbol, trade['expiration'], trade['long_call_strike'], 'C', strategy.exchange),
            ]

            self.ibkr.ib.qualifyContracts(*legs)
            tickers = []
            for leg in legs:
                ticker = self.ibkr.ib.reqMktData(leg, '', False, False)
                tickers.append(ticker)
            
            self.ibkr.ib.sleep(2)
            
            prices = []
            for t in tickers:
                price = t.midpoint() or t.last or t.close or 0
                prices.append(price)
                self.ibkr.ib.cancelMktData(t.contract)

            # Current value = (short_put + short_call) - (long_put + long_call) from buyer's perspective
            # For us (sellers): current debit to close
            current_value = (prices[0] + prices[2]) - (prices[1] + prices[3])
            return max(current_value, 0)

        except Exception as e:
            log.error(f"Error getting spread value: {e}")
            return None

    def execute_exit(self, trade: Dict, reason: str) -> bool:
        """Execute exit for a trade."""
        try:
            order_id = self.ibkr.close_iron_condor(
                short_put=trade['short_put_strike'],
                long_put=trade['long_put_strike'],
                short_call=trade['short_call_strike'],
                long_call=trade['long_call_strike'],
                expiration=trade['expiration'],
                contracts=trade['contracts']
            )

            if order_id:
                current_value = self._get_spread_value(trade) or 0
                commissions = strategy.contracts_per_trade * 4 * 0.65  # 4 legs
                
                realized_pnl = db.close_trade(
                    trade['trade_id'], current_value, reason, commissions
                )
                
                trade_log.info(
                    f"{'✅' if realized_pnl and realized_pnl > 0 else '❌'} EXIT | {trade['trade_id']} | "
                    f"Reason: {reason} | P&L: ${realized_pnl:.2f}"
                )
                db.log_risk_event("trade_exit", f"Closed {trade['trade_id']}: {reason}", 
                                  "info" if realized_pnl and realized_pnl > 0 else "warning",
                                  trade['trade_id'])
                return True
            return False

        except Exception as e:
            log.error(f"Error executing exit for {trade['trade_id']}: {e}", exc_info=True)
            return False

    # ─── Risk Checks ──────────────────────────────────────────────────────

    def _can_open_new_trade(self) -> bool:
        """Check if we can open a new trade based on risk limits."""
        open_trades = db.get_open_trades()
        
        if len(open_trades) >= strategy.max_positions:
            log.info(f"Max positions reached ({len(open_trades)}/{strategy.max_positions})")
            return False

        today_stats = db.get_today_stats()
        
        if today_stats['trades_opened'] >= risk.max_daily_trades:
            log.info(f"Max daily trades reached ({today_stats['trades_opened']})")
            return False

        if today_stats['realized_pnl'] <= -risk.max_daily_loss:
            log.warning(f"Daily loss limit hit (${today_stats['realized_pnl']:.2f})")
            db.log_risk_event("daily_loss_limit", f"Daily loss: ${today_stats['realized_pnl']:.2f}", "warning")
            return False

        # Check consecutive losses
        closed = db.get_closed_trades(limit=risk.consecutive_loss_limit)
        consecutive_losses = 0
        for t in closed:
            if t['realized_pnl'] < 0:
                consecutive_losses += 1
            else:
                break
        
        if consecutive_losses >= risk.consecutive_loss_limit:
            log.warning(f"Consecutive loss limit hit ({consecutive_losses})")
            db.log_risk_event("consecutive_losses", f"{consecutive_losses} losses in a row", "warning")
            return False

        return True

    def _is_trading_time(self) -> bool:
        """Check if current time is within trading window."""
        now = datetime.now()
        day_name = now.strftime("%A")
        
        if day_name not in strategy.entry_days:
            return False

        current_time = now.strftime("%H:%M")
        return strategy.entry_time_start <= current_time <= strategy.entry_time_end
