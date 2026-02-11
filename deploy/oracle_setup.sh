#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# IBKR Iron Condor Bot — Oracle Cloud Free Tier Setup
# ══════════════════════════════════════════════════════════════════════════════
#
# This script sets up an Oracle Cloud Always-Free VM to run the trading bot.
#
# Prerequisites:
#   1. Oracle Cloud account (free tier)
#   2. Create an ARM-based VM: VM.Standard.A1.Flex (4 OCPU, 24GB RAM free)
#      - Image: Canonical Ubuntu 22.04 Minimal aarch64
#   3. SSH into the instance
#   4. Copy this entire project to the server
#   5. Run: chmod +x deploy/oracle_setup.sh && ./deploy/oracle_setup.sh
#
# After setup:
#   1. Edit .env file with your IBKR credentials
#   2. Run: docker compose up -d
#   3. Access dashboard at http://<your-ip>:5000
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

echo "════════════════════════════════════════════════════════════════"
echo "  🦅 Iron Condor Bot — Oracle Cloud Setup"
echo "════════════════════════════════════════════════════════════════"

# ── 1. System Update ─────────────────────────────────────────────────────────
echo ""
echo "▸ Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y
sudo apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    htop \
    ufw

# ── 2. Install Docker ────────────────────────────────────────────────────────
echo ""
echo "▸ Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm get-docker.sh
    sudo usermod -aG docker $USER
    echo "   ✅ Docker installed"
else
    echo "   ✅ Docker already installed"
fi

# ── 3. Install Docker Compose ────────────────────────────────────────────────
echo ""
echo "▸ Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    sudo apt-get install -y docker-compose-plugin
    echo "   ✅ Docker Compose installed"
else
    echo "   ✅ Docker Compose already installed"
fi

# ── 4. Configure Firewall ────────────────────────────────────────────────────
echo ""
echo "▸ Configuring firewall..."
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 5000/tcp    # Dashboard
sudo ufw --force enable
echo "   ✅ Firewall configured (ports 22, 5000)"

# ── 5. Oracle Cloud iptables (required for OCI) ──────────────────────────────
echo ""
echo "▸ Configuring Oracle Cloud iptables..."
sudo iptables -I INPUT -p tcp --dport 5000 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 4001 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 4002 -j ACCEPT

# Make iptables persistent
sudo apt-get install -y iptables-persistent
sudo netfilter-persistent save
echo "   ✅ iptables configured"

# ── 6. Create .env file ──────────────────────────────────────────────────────
echo ""
echo "▸ Creating .env configuration..."
if [ ! -f .env ]; then
    cat > .env << 'ENV_FILE'
# ═══════════════════════════════════════════════════════════════
# IBKR Iron Condor Bot — Environment Configuration
# ═══════════════════════════════════════════════════════════════

# ── IBKR Credentials ─────────────────────────────────────────
# Your Interactive Brokers username and password
IB_USERNAME=your_ib_username
IB_PASSWORD=your_ib_password

# ── Trading Mode ─────────────────────────────────────────────
# "paper" for paper trading, "live" for real money
TRADING_MODE=paper
BOT_ENV=paper

# ── IB Gateway Port ──────────────────────────────────────────
# 4002 = paper trading, 4001 = live trading
IB_PORT=4002

# ── Dashboard ────────────────────────────────────────────────
DASHBOARD_SECRET=your-secret-key-here

# ── VNC Password (for IB Gateway debugging) ──────────────────
VNC_PASSWORD=your-vnc-password
ENV_FILE
    echo "   ✅ .env created — EDIT THIS FILE with your IBKR credentials!"
else
    echo "   ✅ .env already exists"
fi

# ── 7. Create data directories ───────────────────────────────────────────────
echo ""
echo "▸ Creating data directories..."
mkdir -p data logs
echo "   ✅ Directories created"

# ── 8. Setup auto-restart on reboot ──────────────────────────────────────────
echo ""
echo "▸ Configuring auto-restart..."
sudo systemctl enable docker

# Create systemd service for the bot
sudo tee /etc/systemd/system/iron-condor-bot.service > /dev/null << 'SERVICE'
[Unit]
Description=Iron Condor Trading Bot
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/ibkr-iron-condor
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
User=ubuntu

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable iron-condor-bot.service
echo "   ✅ Auto-restart configured"

# ── 9. Setup log rotation ────────────────────────────────────────────────────
echo ""
echo "▸ Configuring log rotation..."
sudo tee /etc/logrotate.d/iron-condor-bot > /dev/null << 'LOGROTATE'
/home/ubuntu/ibkr-iron-condor/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    copytruncate
}
LOGROTATE
echo "   ✅ Log rotation configured (14 days)"

# ── 10. Setup monitoring cron ────────────────────────────────────────────────
echo ""
echo "▸ Setting up health monitoring..."
cat > /home/ubuntu/check_bot.sh << 'HEALTHCHECK'
#!/bin/bash
# Check if bot dashboard is responding
if ! curl -sf http://localhost:5000/api/status > /dev/null 2>&1; then
    echo "[$(date)] Bot health check failed — restarting..."
    cd /home/ubuntu/ibkr-iron-condor
    docker compose restart bot
fi
HEALTHCHECK
chmod +x /home/ubuntu/check_bot.sh

# Add to crontab (check every 5 minutes)
(crontab -l 2>/dev/null; echo "*/5 * * * * /home/ubuntu/check_bot.sh >> /home/ubuntu/ibkr-iron-condor/logs/healthcheck.log 2>&1") | crontab -
echo "   ✅ Health monitoring configured (every 5 min)"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  ✅ Setup Complete!"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Edit credentials:   nano .env"
echo "  2. Build & start:      docker compose up -d --build"
echo "  3. Check status:       docker compose ps"
echo "  4. View logs:          docker compose logs -f bot"
echo "  5. Open dashboard:     http://$(curl -s ifconfig.me):5000"
echo ""
echo "  Useful commands:"
echo "    docker compose logs -f           # All logs"
echo "    docker compose restart bot       # Restart bot"
echo "    docker compose down              # Stop everything"
echo "    docker compose up -d --build     # Rebuild & start"
echo ""
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  ⚠️  IMPORTANT: Configure Oracle Cloud Security List"
echo "  Add an Ingress Rule for port 5000 (TCP) in your"
echo "  VCN's Security List to access the dashboard externally."
echo ""
echo "════════════════════════════════════════════════════════════════"
