#!/usr/bin/env bash
set -e

# Deploy changed files to the GCP VM and restart Docker containers.
# Uses IAP tunnel (port 22 is blocked from outside GCP).
# Run from Mac with: bash scripts/deploy_gcp.sh
# Must be authenticated: gcloud auth login && gcloud config set project project-7b13e461-f96b-4c6f-84e

ZONE="asia-south1-a"
VM="trading-engine"
REMOTE_DIR="/home/jiyanshusingh1/trading-engine"
IAP="--tunnel-through-iap"

echo "=== Deploying to GCP: $VM ==="
echo ""

FILES=(
  "scripts/paper_trade.py"
  "scripts/market_scan.py"
  "data/upstox/upstox_live_feed.py"
  "scripts/deploy_gcp.sh"
)

for f in "${FILES[@]}"; do
  if [ ! -f "$f" ]; then
    echo "  [error] $f not found — are you in the project root?"
    exit 1
  fi
  echo "  Copying $f -> $VM:/tmp/$(basename $f)"
  gcloud compute scp "$f" "$VM:/tmp/$(basename $f)" --zone "$ZONE" $IAP --quiet
done

echo ""
echo "=== Files on VM. Moving to $REMOTE_DIR and rebuilding... ==="
echo ""

gcloud compute ssh "$VM" --zone "$ZONE" $IAP --command "
  set -e
  for f in paper_trade.py market_scan.py upstox_live_feed.py deploy_gcp.sh; do
    if sudo cp /tmp/\$f $REMOTE_DIR/scripts/\$f 2>/dev/null; then
      echo \"  Moved scripts/\$f\"
    elif sudo cp /tmp/\$f $REMOTE_DIR/data/upstox/\$f 2>/dev/null; then
      echo \"  Moved data/upstox/\$f\"
    elif sudo cp /tmp/\$f $REMOTE_DIR/\$f 2>/dev/null; then
      echo \"  Moved root/\$f\"
    else
      echo \"  WARN: could not find destination for \$f\"
    fi
  done
  sudo chown -R jiyanshusingh1:jiyanshusingh1 $REMOTE_DIR/scripts/ $REMOTE_DIR/data/upstox/ 2>/dev/null || true
  sudo bash -c \"cd $REMOTE_DIR && echo '  Stopping containers...' && \
    docker compose down --timeout 30 2>/dev/null || true && \
    echo '  Rebuilding image...' && \
    docker compose build && \
    echo '  Starting containers...' && \
    docker compose up -d && \
    echo '  Done.'\"
"

echo ""
echo "=== Deployment complete ==="
echo "  Check logs: gcloud compute ssh $VM --zone $ZONE $IAP -- 'sudo docker logs trading-engine-paper-trader-1 --tail 50'"
echo "  Dashboard: http://35.200.195.152:8080/"
