#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

echo "=== Stopping Trading Processes ==="

STOPPED=0
for p in paper_trade market_scan refresh_data_cache; do
  PIDS=$(pgrep -f "scripts/${p}.py" 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    for pid in $PIDS; do
      echo "  Stopping $p (PID $pid)..."
      kill "$pid" 2>/dev/null || true
      STOPPED=1
    done
  else
    echo "  $p — not running"
  fi
done

if [ "$STOPPED" -eq 1 ]; then
  sleep 2
  echo "  All processes stopped."
else
  echo "  Nothing to stop."
fi

echo ""
echo "=== Export trades before restart? ==="
echo "  .venv/bin/python scripts/export_trades.py"
echo ""
