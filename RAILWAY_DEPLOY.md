# 🚂 Railway.app Deployment Guide — IBKR Iron Condor Bot

## What You Get

| Component | Runs On |
|-----------|---------|
| Dashboard (Flask) | Railway (public URL) |
| Trading Bot | Railway (background process) |
| IB Gateway | Railway (same container) |
| SQLite Database | Railway persistent volume |

---

## Step 1 — Push Code to GitHub

Railway deploys from a Git repo. Push this project to GitHub:

```bash
cd ibkr-iron-condor

git init
git add .
git commit -m "IBKR Iron Condor Bot"

# Create a repo on GitHub, then:
git remote add origin https://github.com/YOUR_USER/ibkr-iron-condor.git
git branch -M main
git push -u origin main
```

---

## Step 2 — Create Railway Project

1. Go to [railway.app](https://railway.app) and sign in
2. Click **"New Project"**
3. Select **"Deploy from GitHub Repo"**
4. Select your `ibkr-iron-condor` repository
5. Railway will detect the `railway.toml` and use `Dockerfile.railway`

---

## Step 3 — Add Environment Variables

In your Railway project, go to **Variables** tab and add:

| Variable | Value | Required |
|----------|-------|----------|
| `IB_USERNAME` | Your IBKR username | ✅ |
| `IB_PASSWORD` | Your IBKR password | ✅ |
| `TRADING_MODE` | `paper` | ✅ |
| `BOT_ENV` | `paper` | ✅ |
| `IB_PORT` | `4002` | ✅ |
| `IB_HOST` | `127.0.0.1` | ✅ |
| `IB_CLIENT_ID` | `1` | ✅ |
| `DASHBOARD_SECRET` | any random string | ✅ |
| `DB_PATH` | `/app/data/trades.db` | ✅ |

> ⚠️ **Start with `paper` mode!** Only switch to `live` after 30+ days.

### Quick copy-paste for Railway CLI:
```bash
railway variables set IB_USERNAME=your_username
railway variables set IB_PASSWORD=your_password
railway variables set TRADING_MODE=paper
railway variables set BOT_ENV=paper
railway variables set IB_PORT=4002
railway variables set IB_HOST=127.0.0.1
railway variables set IB_CLIENT_ID=1
railway variables set DASHBOARD_SECRET=my-secret-key-123
railway variables set DB_PATH=/app/data/trades.db
```

---

## Step 4 — Add Persistent Volume

Your trade database needs to survive redeployments:

1. In your Railway service, click **"+ New"** → **"Volume"**
2. Set **Mount Path** to: `/app/data`
3. Click **"Add"**

This ensures `trades.db` persists across deployments.

---

## Step 5 — Deploy

Railway auto-deploys on every push. To trigger manually:

1. Go to your service in Railway dashboard
2. Click **"Deploy"** → **"Trigger Deploy"**

Or via CLI:
```bash
railway up
```

---

## Step 6 — Get Your Dashboard URL

1. In your Railway service, go to **Settings** tab
2. Under **Networking** → **Public Networking**
3. Click **"Generate Domain"**
4. Railway gives you a URL like: `https://ibkr-iron-condor-production-xxxx.up.railway.app`

Open that URL — you should see the Iron Condor dashboard! 🎉

---

## Step 7 — Verify Everything Works

### Check the dashboard
Open your Railway URL. You should see:
- **Overview** tab with P&L cards
- **Positions** tab (empty initially)
- **Backtest** tab — try running one!

### Check logs
In Railway dashboard → **Deployments** → click latest → **View Logs**

Or via CLI:
```bash
railway logs
```

You should see:
```
▸ Starting IB Gateway...
  Mode:  paper
  Port:  4002
🚀 Iron Condor Bot initializing | Mode: PAPER
🌐 Dashboard running at http://0.0.0.0:xxxx
```

---

## Step 8 — Run a Backtest

1. Open your dashboard URL
2. Click the **"🧪 Backtest"** tab
3. Set date range (e.g., 2023-01-01 to 2025-01-01)
4. Set initial capital (e.g., $50,000)
5. Click **"Run Backtest"**
6. Review: equity curve, win rate, Sharpe ratio, monthly P&L

---

## Common Operations

### View logs
```bash
railway logs                     # Live logs
railway logs --tail 200          # Last 200 lines
```

### Restart service
```bash
railway service restart
```

### Update code & redeploy
```bash
git add .
git commit -m "update strategy"
git push                         # Auto-deploys
```

### Switch to live trading
In Railway **Variables**, change:
```
TRADING_MODE=live
BOT_ENV=live
IB_PORT=4001
```
Railway auto-redeploys on variable change.

---

## IB Gateway Connection Notes

### Option A: All-in-One (Default)
The `Dockerfile.railway` bundles IB Gateway inside the same container. This is the simplest setup — IB Gateway runs headlessly alongside your bot.

- ✅ Single container, no external dependencies
- ✅ `IB_HOST=127.0.0.1` just works
- ⚠️ IB Gateway may need periodic restarts (IBKR sessions expire)

### Option B: External IB Gateway
If you prefer running IB Gateway separately (e.g., on your local PC or another server):

1. Run IB Gateway/TWS on your machine
2. Expose it via [ngrok](https://ngrok.com) or Cloudflare Tunnel:
   ```bash
   ngrok tcp 4002
   ```
3. Set Railway variables:
   ```
   IB_HOST=0.tcp.ngrok.io  (your ngrok host)
   IB_PORT=xxxxx           (your ngrok port)
   ```

### Option C: Dashboard-Only Mode
If IB Gateway isn't available, the bot runs in dashboard-only mode:
- Dashboard works fully (backtest, config, history)
- Trading engine pauses until IB Gateway reconnects
- No trades placed, no errors — just waits

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Build fails | Check Railway build logs. Ensure `Dockerfile.railway` exists. |
| Dashboard shows but bot says "stopped" | IB Gateway may not have connected yet. Check logs for IBKR errors. Verify credentials. |
| "Cannot connect to IBKR" | Verify `IB_USERNAME` and `IB_PASSWORD` are correct. Check IBKR API is enabled in your account settings. |
| Backtest works but live doesn't | IB Gateway needs active market data subscription for SPY options. |
| Volume data lost | Ensure Railway Volume is mounted at `/app/data`. |
| Gateway disconnects daily | Normal — IBKR sessions expire. Bot auto-reconnects. If persistent, restart: `railway service restart` |
| High memory usage | IB Gateway + Python uses ~1-2GB. Railway free tier has 512MB limit — upgrade to Developer plan ($5/mo, 8GB RAM). |

---

## Railway Plans & Costs

| Plan | RAM | Cost | Good For |
|------|-----|------|----------|
| **Trial** | 512MB | Free (500 hrs) | Testing only |
| **Developer** | 8GB | $5/mo + usage | ✅ Recommended |
| **Pro** | 32GB | $20/mo + usage | Multiple bots |

> **Recommendation:** The Developer plan at $5/month is ideal. IB Gateway + Bot + Dashboard typically uses ~1.5GB RAM and minimal CPU.

---

## Quick Reference

```
Dashboard:  https://your-app.up.railway.app
Logs:       railway logs
Restart:    railway service restart
Redeploy:   git push (auto-deploys)
Variables:  Railway Dashboard → Variables tab
Volume:     Mounted at /app/data
```
