# 🦅 IBKR Iron Condor Bot

Automated SPY Iron Condor options trading bot for Interactive Brokers with backtesting engine, real-time monitoring dashboard, and Oracle Cloud Free Tier deployment.

## Features

- **Auto Entry**: Delta-targeted Iron Condor construction on SPY
- **Auto Exit**: Profit target, stop loss, DTE-based, and wing breach exits
- **Risk Management**: Daily/weekly limits, drawdown protection, consecutive loss halts, VIX filters
- **Backtesting**: Black-Scholes based simulation with slippage and commissions
- **Dashboard**: Real-time web UI with equity curves, P&L charts, position monitoring
- **Deployment**: Docker + Oracle Cloud Free Tier with auto-restart and health checks

## Architecture

```
ibkr-iron-condor/
├── main.py                    # Entry point (bot + dashboard)
├── config/settings.py         # All configurable parameters
├── strategies/iron_condor.py  # Strategy engine (entry/exit/risk)
├── backtesting/engine.py      # Historical simulation engine
├── dashboard/app.py           # Flask REST API + web dashboard
├── utils/
│   ├── ibkr_connection.py     # IBKR TWS/Gateway connector
│   ├── database.py            # SQLite trade storage
│   └── logger.py              # Logging setup
├── templates/dashboard.html   # Dashboard UI
├── deploy/
│   ├── oracle_setup.sh        # Oracle Cloud setup script
│   └── supervisord.conf       # Process manager config
├── docker-compose.yml         # Full stack deployment
├── Dockerfile                 # Container build
└── requirements.txt           # Python dependencies
```

## Quick Start

### 1. Local Development (Paper Trading)

```bash
# Install dependencies
pip install -r requirements.txt

# Start IB Gateway or TWS (paper trading mode, port 4002)

# Run backtest first
python main.py --backtest

# Run dashboard only (no trading)
python main.py --dashboard

# Run bot + dashboard
python main.py
```

### 2. Docker (Recommended)

```bash
# Copy and edit environment variables
cp .env.example .env
nano .env  # Add your IBKR credentials

# Start everything
docker compose up -d --build

# View logs
docker compose logs -f bot

# Access dashboard
open http://localhost:5000
```

### 3. Oracle Cloud Free Tier Deployment

```bash
# SSH into your Oracle Cloud VM
ssh ubuntu@<your-instance-ip>

# Clone the project
git clone <your-repo> ibkr-iron-condor
cd ibkr-iron-condor

# Run setup script
chmod +x deploy/oracle_setup.sh
./deploy/oracle_setup.sh

# Edit credentials
nano .env

# Build and start
docker compose up -d --build

# Dashboard: http://<your-ip>:5000
```

**Oracle Cloud Setup Checklist:**
1. Create Always-Free VM: `VM.Standard.A1.Flex` (4 OCPU, 24GB RAM)
2. Use Ubuntu 22.04 Minimal (aarch64)
3. Add Security List Ingress Rule for port **5000** (TCP)
4. Run the setup script
5. The bot auto-restarts on reboot

## Configuration

All parameters are in `config/settings.py`:

### Strategy Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `short_put_delta` | -0.16 | Short put delta target |
| `short_call_delta` | 0.16 | Short call delta target |
| `wing_width` | $5 | Width of protective wings |
| `target_dte_min` | 30 | Minimum days to expiration |
| `target_dte_max` | 45 | Maximum days to expiration |
| `min_credit` | $0.80 | Minimum credit to collect |
| `profit_target_pct` | 50% | Close at % of max profit |
| `stop_loss_pct` | 200% | Close at % of premium lost |
| `dte_exit` | 7 days | Close when DTE falls below |
| `max_positions` | 3 | Max concurrent iron condors |

### Risk Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_daily_loss` | $500 | Halt trading after daily loss |
| `max_daily_trades` | 3 | Max new trades per day |
| `max_drawdown_pct` | 10% | Max portfolio drawdown |
| `consecutive_loss_limit` | 3 | Halt after N losses in a row |
| `vix_max_entry` | 35 | Don't trade when VIX > 35 |
| `vix_min_entry` | 12 | Don't trade when VIX < 12 |

## Dashboard

Access at `http://localhost:5000` with tabs for:

- **Overview**: Today's P&L, equity curve, monthly returns, risk events
- **Positions**: Open iron condor positions with DTE, unrealized P&L
- **History**: Complete trade log with exit reasons
- **Backtest**: Run historical simulations with custom parameters
- **Settings**: Current bot configuration display

### API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Bot status and daily summary |
| `/api/positions` | GET | Open positions |
| `/api/trades` | GET | Trade history |
| `/api/pnl` | GET | Daily P&L data |
| `/api/risk-events` | GET | Risk event log |
| `/api/backtest` | POST | Run backtest |
| `/api/config` | GET | Current configuration |

## Iron Condor Strategy Logic

### Entry Rules
1. Check trading schedule (Mon-Wed, 10:00-15:30 ET)
2. Verify position limits and risk budgets
3. Find expiration in 30-45 DTE range
4. Select short put at ~16 delta, short call at ~16 delta
5. Add $5-wide protective wings
6. Verify minimum credit collected ($0.80+)
7. Execute as combo limit order

### Exit Rules (checked every 60s)
1. **Profit Target**: Close when spread value drops to 50% of credit
2. **Stop Loss**: Close when spread value rises to 200% of credit
3. **DTE Exit**: Close when ≤7 DTE (avoid gamma risk)
4. **Wing Breach**: Close if price touches long strikes

## Backtesting

The backtesting engine uses Black-Scholes pricing with:
- Historical SPY data from Yahoo Finance
- Seasonal IV estimation
- Realistic slippage modeling (2%)
- Commission costs ($0.65/contract/leg)
- All strategy exit rules applied

```bash
# Run from command line
python main.py --backtest

# Or from Python
from backtesting.engine import run_backtest
result = run_backtest(start="2022-01-01", end="2025-01-01", capital=50000)
```

## Safety & Disclaimers

⚠️ **IMPORTANT**: This bot trades real money when in live mode. Always:
1. **Paper trade first** for at least 30 days
2. **Start with minimum position sizes** (1 contract)
3. **Monitor the dashboard daily**
4. **Understand iron condor risks** before deploying
5. **Never risk more than you can afford to lose**

This software is provided as-is with no warranty. Trading options involves substantial risk of loss. Past backtest performance does not guarantee future results.
