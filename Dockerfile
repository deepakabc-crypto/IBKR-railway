# ── IBKR Iron Condor Bot ──────────────────────────────────────────────────────
# Multi-stage build: IB Gateway + Python Bot + Dashboard
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

LABEL maintainer="iron-condor-bot"
LABEL description="IBKR SPY Iron Condor Trading Bot with Dashboard"

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl unzip supervisor cron \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ──────────────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ─────────────────────────────────────────────────────────
COPY . .

# ── Create directories ───────────────────────────────────────────────────────
RUN mkdir -p /app/data /app/logs

# ── Supervisor config (runs bot + dashboard) ─────────────────────────────────
COPY deploy/supervisord.conf /etc/supervisor/conf.d/bot.conf

# ── Environment defaults ─────────────────────────────────────────────────────
ENV BOT_ENV=paper \
    IB_HOST=127.0.0.1 \
    IB_PORT=4002 \
    IB_CLIENT_ID=1 \
    DASHBOARD_SECRET=change-me-in-production \
    DB_PATH=/app/data/trades.db \
    PYTHONUNBUFFERED=1

EXPOSE 5000

# ── Health check ──────────────────────────────────────────────────────────────
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/status || exit 1

# ── Entry point ───────────────────────────────────────────────────────────────
CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/bot.conf"]
