#!/bin/bash
# ══════════════════════════════════════════════════════════════
# IB Gateway Startup Script for Railway
# Runs IB Gateway headlessly with Xvfb virtual display
# ══════════════════════════════════════════════════════════════
set -e

echo "▸ Starting IB Gateway..."

# ── Determine ports based on trading mode ─────────────────────
if [ "$TRADING_MODE" = "live" ]; then
    API_PORT=4001
    MODE_FLAG="live"
else
    API_PORT=4002
    MODE_FLAG="paper"
fi

echo "  Mode:  $MODE_FLAG"
echo "  Port:  $API_PORT"

# ── Start virtual display ────────────────────────────────────
Xvfb :99 -screen 0 1024x768x24 -nolisten tcp &
sleep 2
echo "  ✅ Xvfb started on :99"

# ── Update IB Gateway config ─────────────────────────────────
INI_FILE="/opt/ibgateway/jts/jts.ini"
if [ -f "$INI_FILE" ]; then
    sed -i "s/^LocalServerPort=.*/LocalServerPort=$API_PORT/" "$INI_FILE"
    sed -i "s/^Trading Mode=.*/Trading Mode=$MODE_FLAG/" "$INI_FILE"
fi

# ── Find IB Gateway executable ───────────────────────────────
GW_DIR="/opt/ibgateway"
GW_SCRIPT=$(find "$GW_DIR" -name "ibgateway" -type f 2>/dev/null | head -1)

if [ -z "$GW_SCRIPT" ]; then
    # Try finding the jar file directly
    GW_JAR=$(find "$GW_DIR" -name "ibgateway-*.jar" -o -name "jars/ibgateway*.jar" 2>/dev/null | head -1)
    if [ -n "$GW_JAR" ]; then
        echo "  Starting via JAR: $GW_JAR"
        exec java -cp "$GW_JAR:$GW_DIR/jars/*" ibgateway.GWStarter "$GW_DIR"
    else
        echo "  ⚠️ IB Gateway not found — running in dashboard-only mode"
        echo "  Set IB_HOST to external IB Gateway address in Railway variables"
        # Keep process alive so supervisor doesn't restart endlessly
        exec tail -f /dev/null
    fi
fi

echo "  Starting: $GW_SCRIPT"
exec "$GW_SCRIPT"
