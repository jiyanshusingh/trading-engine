#!/bin/bash
set -u

DATE=$(date +%F)
DATA_SRC="/var/lib/docker/volumes/trading-engine_trading_data/_data"
BACKUP_DIR="$HOME/trading-data-backup"
SSH_KEY="$HOME/.ssh/trades_backup"
SUDO="sudo"

mkdir -p "$BACKUP_DIR/trades" "$BACKUP_DIR/state"

if ! $SUDO test -f "$DATA_SRC/trade_history.json"; then
  echo "[$DATE] No trade_history.json yet — skipping backup"
  exit 0
fi

$SUDO cp "$DATA_SRC/trade_history.json" "$BACKUP_DIR/trades/trades_$DATE.json"
$SUDO cp "$DATA_SRC/paper_portfolio.json" "$BACKUP_DIR/state/latest.json"

for f in trade_state.json pending_orders.jsonl; do
  $SUDO test -f "$DATA_SRC/$f" && $SUDO cp "$DATA_SRC/$f" "$BACKUP_DIR/state/" || true
done

$SUDO chown -R "$(whoami):$(whoami)" "$BACKUP_DIR"

cd "$BACKUP_DIR"
GIT_SSH_COMMAND="ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  git add -A && \
  git commit -m "daily backup $DATE" --quiet && \
  git push origin main --quiet

echo "[$DATE] backup OK — $(wc -c < "$BACKUP_DIR/trades/trades_$DATE.json") bytes"
