#!/bin/bash
set -e

DATE=$(date +%F)
DATA_SRC="/var/lib/docker/volumes/trading-engine_trading_data/_data"
BACKUP_DIR="$HOME/trading-data-backup"
SSH_KEY="$HOME/.ssh/trades_backup"

mkdir -p "$BACKUP_DIR/trades" "$BACKUP_DIR/state"

if [ ! -f "$DATA_SRC/trade_history.json" ]; then
  echo "[$DATE] WARN: trade_history.json not found at $DATA_SRC — is the volume mounted?"
  exit 1
fi

cp "$DATA_SRC/trade_history.json" "$BACKUP_DIR/trades/trades_$DATE.json"
cp "$DATA_SRC/paper_portfolio.json" "$BACKUP_DIR/state/latest.json"

for f in trade_state.json pending_orders.jsonl; do
  [ -f "$DATA_SRC/$f" ] && cp "$DATA_SRC/$f" "$BACKUP_DIR/state/"
done

cd "$BACKUP_DIR"
GIT_SSH_COMMAND="ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  git add -A && \
  git commit -m "daily backup $DATE" --quiet && \
  git push origin main --quiet

echo "[$DATE] backup OK — $(wc -c < "$BACKUP_DIR/trades/trades_$DATE.json") bytes"
