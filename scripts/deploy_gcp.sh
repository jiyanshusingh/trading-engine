#!/usr/bin/env bash
set -e

# Deploy the 4 changed files to the GCP VM and restart Docker containers.
# Run this from Cloud Shell (gcloud CLI required).
# Usage: cd /path/to/deploy && bash deploy_gcp.sh

ZONE="asia-south1-a"
VM="trading-engine"
REMOTE_DIR="/home/jiyanshusingh1/trading-engine"

echo "=== Deploying to GCP: $VM ==="
echo ""

FILES=(
  "scripts/paper_trade.py"
  "scripts/start_all.sh"
  "data/upstox/upstox_live_feed.py"
  "docker-compose.yml"
)

for f in "${FILES[@]}"; do
  if [ ! -f "$f" ]; then
    echo "  [error] $f not found — are you in the project root?"
    exit 1
  fi
  echo "  Copying $f -> $VM:$REMOTE_DIR/$f"
  gcloud compute scp "$f" "$VM:$REMOTE_DIR/$f" --zone "$ZONE" --quiet
done

echo ""
echo "=== Files copied. Rebuilding Docker image on VM... ==="
echo ""

gcloud compute ssh "$VM" --zone "$ZONE" --command "
  cd $REMOTE_DIR
  echo '  Stopping containers...'
  sudo docker compose down --timeout 30 2>/dev/null || true
  echo '  Rebuilding image...'
  sudo docker compose build
  echo '  Starting containers (with --reset for fresh ₹100k allocation)...'
  sudo docker compose up -d
  echo '  Done.'
"

echo ""
echo "=== Deployment complete ==="
echo "  Check logs: gcloud compute ssh $VM --zone $ZONE -- 'sudo docker logs trading-engine-paper-trader-1 --tail 50'"
echo "  Dashboard: http://35.200.195.152:8080/"
