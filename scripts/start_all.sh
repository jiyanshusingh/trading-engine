#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

LOG_DIR="data"
mkdir -p "$LOG_DIR"

echo "=== Starting Institutional Trading AI ==="
echo ""

# Kill any existing instances first
echo "Stopping any existing processes..."
for p in market_scan paper_trade refresh_data_cache; do
  for pid in $(pgrep -f "scripts/${p}.py" 2>/dev/null); do
    echo "  Killing $p (PID $pid)"
    kill "$pid" 2>/dev/null || true
  done
done
sleep 2

echo ""
echo "Starting scanner + dashboard..."
nohup venv/bin/python -u scripts/market_scan.py \
  --upstox --serve --port 8080 \
  > "$LOG_DIR/market_scan.log" 2>&1 &
SCANNER_PID=$!
echo "  Scanner PID: $SCANNER_PID"

sleep 1

# LIVE=1 ./scripts/start_all.sh  → add --real (places REAL Upstox orders).
# Requires a static IP registered with Upstox (see AGENTS.md Phase 20).
# Default (LIVE unset) = paper only.
REAL_FLAG=""
if [ "${LIVE:-0}" = "1" ]; then
  REAL_FLAG="--real"
  echo ""
  echo "  ############################################################"
  echo "  ##  LIVE=1 → REAL ORDERS ENABLED (real money, --real)     ##"
  echo "  ############################################################"
fi

# RESET=1 ./scripts/start_all.sh  → wipe paper state (fresh allocations).
# Use after changing --strategies/--alloc so cash splits cleanly.
RESET_FLAG=""
if [ "${RESET:-0}" = "1" ]; then
  RESET_FLAG="--reset"
  echo "  RESET=1 → paper portfolio will be wiped (fresh ₹50k allocations)"
fi

echo "Starting paper trader..."
nohup venv/bin/python -u scripts/paper_trade.py \
  --strategies "Relative Strength Momentum,Combined Swing,Manual Institutional (time-gated),ML Standalone,Daily Trend Breakout,ML Opening Breakout" \
  --alloc 18,22,18,14,18,10 \
  --sl 1.0,2.0,0.5,0.5,4.0,0.5 \
  --tp 2.5,4.0,5.0,5.0,5.0,5.0 \
  --mode both \
  --ml-filter --ml-filter-thr 0.60 \
  --upstox $REAL_FLAG $RESET_FLAG --loop --interval 5 \
  > "$LOG_DIR/paper_trade.log" 2>&1 &
PAPER_PID=$!
echo "  Paper trader PID: $PAPER_PID"

sleep 1

# Data-cache refresher: fetches TRUE NATIVE candles (1m/15m/30m/1h/1d) for the
# full NSE universe (NIFTY 500 + F&O) from Upstox V3 and merges into the parquet
# cache once per day after market close (16:00 IST). See AGENTS.md Phase 35.
echo "Starting data-cache refresher (daily EOD)..."
nohup venv/bin/python -u scripts/refresh_data_cache.py --loop \
  > "$LOG_DIR/refresh_cache.log" 2>&1 &
REFRESH_PID=$!
echo "  Data refresher PID: $REFRESH_PID"

echo ""
echo "=== Started ==="
echo "  Dashboard:  http://localhost:8080/"
echo "  API:        http://localhost:8080/api/latest"
echo "  Logs:"
echo "    Scanner:      tail -f $LOG_DIR/market_scan.log"
echo "    Paper trader: tail -f $LOG_DIR/paper_trade.log"
echo "    Data refresh: tail -f $LOG_DIR/refresh_cache.log"
echo ""
echo "  To stop:   ./scripts/stop_all.sh"
echo "  To export: venv/bin/python scripts/export_trades.py"
echo ""
echo "  Paper (default):  ./scripts/start_all.sh"
echo "  LIVE real orders: LIVE=1 ./scripts/start_all.sh   (needs Upstox static IP)"
echo ""
