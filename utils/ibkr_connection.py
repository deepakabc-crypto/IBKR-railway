"""
Interactive Brokers Connection Manager
Handles connection lifecycle, reconnection, and market data requests.
"""
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from ib_insync import IB, Stock, Option, Contract, MarketOrder, LimitOrder, ComboLeg, Ticker
from ib_insync import util as ib_util

from config import IB_HOST, IB_PORT, IB_CLIENT_ID, strategy
from utils.logger import log


class IBKRConnection:
    """Manages IBKR TWS/Gateway connection with auto-reconnect."""

    def __init__(self, host: str = None, port: int = None, client_id: int = None):
        self.host = host or IB_HOST
        self.port = port or IB_PORT
        self.client_id = client_id or IB_CLIENT_ID
        self.ib = IB()
        self._connected = False
        self._max_retries = 5
        self._retry_delay = 10

    def connect(self) -> bool:
        """Connect to IBKR with retry logic."""
        for attempt in range(1, self._max_retries + 1):
            try:
                log.info(f"Connecting to IBKR {self.host}:{self.port} (attempt {attempt}/{self._max_retries})")
                self.ib.connect(self.host, self.port, clientId=self.client_id, timeout=20)
                self._connected = True
                log.info(f"✅ Connected to IBKR | Account: {self.ib.managedAccounts()}")
                
                # Set up disconnect handler
                self.ib.disconnectedEvent += self._on_disconnect
                return True
            except Exception as e:
                log.warning(f"Connection attempt {attempt} failed: {e}")
                if attempt < self._max_retries:
                    time.sleep(self._retry_delay)
        
        log.error("❌ Failed to connect to IBKR after all retries")
        return False

    def disconnect(self):
        """Gracefully disconnect."""
        if self.ib.isConnected():
            self.ib.disconnect()
            self._connected = False
            log.info("Disconnected from IBKR")

    def _on_disconnect(self):
        """Handle unexpected disconnection."""
        log.warning("⚠️ IBKR connection lost — attempting reconnect...")
        self._connected = False
        time.sleep(5)
        self.connect()

    @property
    def is_connected(self) -> bool:
        return self.ib.isConnected()

    def ensure_connected(self):
        """Ensure connection is active, reconnect if needed."""
        if not self.is_connected:
            self.connect()

    # ─── Market Data ──────────────────────────────────────────────────────

    def get_spy_contract(self) -> Stock:
        """Get qualified SPY stock contract."""
        contract = Stock(strategy.symbol, strategy.exchange, strategy.currency)
        self.ib.qualifyContracts(contract)
        return contract

    def get_spy_price(self) -> float:
        """Get current SPY mid price."""
        self.ensure_connected()
        contract = self.get_spy_contract()
        ticker = self.ib.reqMktData(contract, '', False, False)
        self.ib.sleep(2)
        
        if ticker.midpoint() and ticker.midpoint() > 0:
            price = ticker.midpoint()
        elif ticker.last and ticker.last > 0:
            price = ticker.last
        elif ticker.close and ticker.close > 0:
            price = ticker.close
        else:
            raise ValueError("Cannot get SPY price — no market data")
        
        self.ib.cancelMktData(contract)
        return price

    def get_option_chains(self, dte_min: int = None, dte_max: int = None) -> List:
        """Get SPY option chains within DTE range."""
        self.ensure_connected()
        dte_min = dte_min or strategy.target_dte_min
        dte_max = dte_max or strategy.target_dte_max
        
        spy = self.get_spy_contract()
        chains = self.ib.reqSecDefOptParams(spy.symbol, '', spy.secType, spy.conId)
        
        if not chains:
            log.error("No option chains returned")
            return []
        
        # Filter for SMART exchange chains
        chain = next((c for c in chains if c.exchange == 'SMART'), chains[0])
        
        now = datetime.now()
        target_start = now + timedelta(days=dte_min)
        target_end = now + timedelta(days=dte_max)
        
        valid_expirations = []
        for exp in chain.expirations:
            exp_date = datetime.strptime(exp, '%Y%m%d')
            if target_start <= exp_date <= target_end:
                valid_expirations.append(exp)
        
        return valid_expirations, chain.strikes

    def get_option_greeks(self, contract: Option) -> Optional[Dict]:
        """Get option greeks for a specific contract."""
        self.ensure_connected()
        self.ib.qualifyContracts(contract)
        ticker = self.ib.reqMktData(contract, '', False, False)
        self.ib.sleep(2)
        
        greeks = None
        if ticker.modelGreeks:
            g = ticker.modelGreeks
            greeks = {
                'delta': g.delta,
                'gamma': g.gamma,
                'theta': g.theta,
                'vega': g.vega,
                'iv': g.impliedVol,
                'price': ticker.midpoint() or ticker.last or 0
            }
        
        self.ib.cancelMktData(contract)
        return greeks

    def find_strike_by_delta(self, expiration: str, right: str, target_delta: float,
                             strikes: List[float], spy_price: float) -> Optional[Dict]:
        """Find the strike closest to target delta."""
        self.ensure_connected()
        
        # Narrow strikes to reasonable range around ATM
        if right == 'P':
            candidate_strikes = [s for s in strikes if spy_price * 0.90 <= s <= spy_price * 1.0]
        else:
            candidate_strikes = [s for s in strikes if spy_price * 1.0 <= s <= spy_price * 1.10]
        
        candidate_strikes = sorted(candidate_strikes)
        
        best_strike = None
        best_diff = float('inf')
        best_greeks = None
        
        for strike in candidate_strikes:
            contract = Option(strategy.symbol, expiration, strike, right, strategy.exchange)
            greeks = self.get_option_greeks(contract)
            
            if greeks and greeks['delta'] is not None:
                diff = abs(abs(greeks['delta']) - abs(target_delta))
                if diff < best_diff:
                    best_diff = diff
                    best_strike = strike
                    best_greeks = greeks
        
        if best_strike:
            return {
                'strike': best_strike,
                'right': right,
                'expiration': expiration,
                'greeks': best_greeks
            }
        return None

    # ─── Order Execution ──────────────────────────────────────────────────

    def place_iron_condor(self, short_put: float, long_put: float,
                          short_call: float, long_call: float,
                          expiration: str, contracts: int = 1,
                          limit_price: float = None) -> Optional[str]:
        """Place an iron condor combo order. Returns order ID or None."""
        self.ensure_connected()
        
        # Create option contracts for all four legs
        sp = Option(strategy.symbol, expiration, short_put, 'P', strategy.exchange)
        lp = Option(strategy.symbol, expiration, long_put, 'P', strategy.exchange)
        sc = Option(strategy.symbol, expiration, short_call, 'C', strategy.exchange)
        lc = Option(strategy.symbol, expiration, long_call, 'C', strategy.exchange)
        
        contracts_list = [sp, lp, sc, lc]
        self.ib.qualifyContracts(*contracts_list)
        
        # Build combo contract
        combo = Contract()
        combo.symbol = strategy.symbol
        combo.secType = 'BAG'
        combo.exchange = strategy.exchange
        combo.currency = strategy.currency
        
        combo.comboLegs = [
            ComboLeg(conId=sp.conId, ratio=1, action='SELL', exchange=strategy.exchange),
            ComboLeg(conId=lp.conId, ratio=1, action='BUY', exchange=strategy.exchange),
            ComboLeg(conId=sc.conId, ratio=1, action='SELL', exchange=strategy.exchange),
            ComboLeg(conId=lc.conId, ratio=1, action='BUY', exchange=strategy.exchange),
        ]
        
        if limit_price:
            order = LimitOrder('SELL', contracts, limit_price)
        else:
            order = MarketOrder('SELL', contracts)
        
        trade = self.ib.placeOrder(combo, order)
        self.ib.sleep(1)
        
        log.info(f"📤 Iron Condor order placed: {short_put}P/{long_put}P/{short_call}C/{long_call}C "
                 f"exp={expiration} qty={contracts}")
        
        return str(trade.order.orderId)

    def close_iron_condor(self, short_put: float, long_put: float,
                          short_call: float, long_call: float,
                          expiration: str, contracts: int = 1) -> Optional[str]:
        """Close an existing iron condor position."""
        self.ensure_connected()
        
        sp = Option(strategy.symbol, expiration, short_put, 'P', strategy.exchange)
        lp = Option(strategy.symbol, expiration, long_put, 'P', strategy.exchange)
        sc = Option(strategy.symbol, expiration, short_call, 'C', strategy.exchange)
        lc = Option(strategy.symbol, expiration, long_call, 'C', strategy.exchange)
        
        contracts_list = [sp, lp, sc, lc]
        self.ib.qualifyContracts(*contracts_list)
        
        combo = Contract()
        combo.symbol = strategy.symbol
        combo.secType = 'BAG'
        combo.exchange = strategy.exchange
        combo.currency = strategy.currency
        
        # Reverse the legs to close
        combo.comboLegs = [
            ComboLeg(conId=sp.conId, ratio=1, action='BUY', exchange=strategy.exchange),
            ComboLeg(conId=lp.conId, ratio=1, action='SELL', exchange=strategy.exchange),
            ComboLeg(conId=sc.conId, ratio=1, action='BUY', exchange=strategy.exchange),
            ComboLeg(conId=lc.conId, ratio=1, action='SELL', exchange=strategy.exchange),
        ]
        
        order = MarketOrder('BUY', contracts)
        trade = self.ib.placeOrder(combo, order)
        self.ib.sleep(1)
        
        log.info(f"📥 Closing Iron Condor: {short_put}P/{long_put}P/{short_call}C/{long_call}C")
        return str(trade.order.orderId)

    def get_account_summary(self) -> Dict:
        """Get account balance information."""
        self.ensure_connected()
        summary = {}
        for av in self.ib.accountValues():
            if av.tag in ('NetLiquidation', 'TotalCashValue', 'BuyingPower',
                          'GrossPositionValue', 'MaintMarginReq', 'UnrealizedPnL', 'RealizedPnL'):
                if av.currency == 'USD':
                    summary[av.tag] = float(av.value)
        return summary

    def get_portfolio_positions(self) -> List[Dict]:
        """Get current portfolio positions."""
        self.ensure_connected()
        positions = []
        for pos in self.ib.positions():
            positions.append({
                'symbol': pos.contract.symbol,
                'secType': pos.contract.secType,
                'strike': getattr(pos.contract, 'strike', None),
                'right': getattr(pos.contract, 'right', None),
                'expiry': getattr(pos.contract, 'lastTradeDateOrContractMonth', None),
                'position': pos.position,
                'avgCost': pos.avgCost,
                'marketValue': getattr(pos, 'marketValue', None)
            })
        return positions
