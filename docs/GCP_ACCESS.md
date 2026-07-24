# GCP Trading Engine — Access Reference

**Project**: `project-7b13e461-f96b-4c6f-84e`
**Instance**: `trading-engine` (`e2-medium`, `35.200.195.152`, zone `asia-south1-a`)
**Setup**: 3 Docker containers running under root on the host

---

## SSH into the VM

```bash
gcloud compute ssh trading-engine --zone asia-south1-a
```

## List running containers

```bash
sudo docker ps
```

| Container ID   | Image               | Service                              |
|----------------|---------------------|--------------------------------------|
| `e27b1eb51c0f` | `trading-engine:latest` | `trading-engine-paper-trader-1`  |
| `ec769eeba4c8` | `trading-engine:latest` | scanner (market_scan.py --serve) |
| `a53c6e04a56c` | `trading-engine:latest` | refresher (refresh_data_cache.py) |

## Common tasks

### Read the paper portfolio state

```bash
sudo docker exec e27b1eb51c0f cat /app/data/paper_portfolio.json
```

### View container logs (last 100 lines)

```bash
sudo docker logs e27b1eb51c0f --tail 100
sudo docker logs ec769eeba4c8 --tail 100
sudo docker logs a53c6e04a56c --tail 100
```

### List files in the shared data volume

```bash
sudo docker exec e27b1eb51c0f ls /app/data/
```

The `trading_data` volume is mounted at `/app/data` in all containers.

### Check running processes

Inside a container:
```bash
sudo docker exec e27b1eb51c0f ps aux
```

On the host:
```bash
ps aux | grep paper_trade
```

### Restart a service

```bash
cd /app && sudo docker compose restart trading-engine-paper-trader-1
cd /app && sudo docker compose restart scanner
cd /app && sudo docker compose restart refresher
```

### Check how a container was started (flags / Cmd)

```bash
sudo docker inspect e27b1eb51c0f | jq '.[0].Config.Cmd'
```

### Quick trade check (one-liner)

```bash
sudo docker exec e27b1eb51c0f python3 -c "
import json
d = json.load(open('/app/data/paper_portfolio.json'))
print(json.dumps(d, indent=2))
"
```

### View all three logs simultaneously

```bash
sudo docker logs e27b1eb51c0f --tail 50
sudo docker logs ec769eeba4c8 --tail 50
sudo docker logs a53c6e04a56c --tail 50
```

## Deploy changes to GCP

After modifying source files locally, deploy to GCP with:

```bash
# 1. Authenticate (one-time, opens browser)
gcloud auth login

# 2. Set project (one-time)
gcloud config set project project-7b13e461-f96b-4c6f-84e

# 3. SCP changed files to VM and rebuild
gcloud compute scp scripts/paper_trade.py trading-engine:/home/jiyanshusingh1/trading-engine/scripts/paper_trade.py --zone asia-south1-a
gcloud compute scp scripts/start_all.sh trading-engine:/home/jiyanshusingh1/trading-engine/scripts/start_all.sh --zone asia-south1-a
gcloud compute scp data/upstox/upstox_live_feed.py trading-engine:/home/jiyanshusingh1/trading-engine/data/upstox/upstox_live_feed.py --zone asia-south1-a
gcloud compute scp docker-compose.yml trading-engine:/home/jiyanshusingh1/trading-engine/docker-compose.yml --zone asia-south1-a

# 4. SSH, rebuild image, restart containers
gcloud compute ssh trading-engine --zone asia-south1-a --command "
  cd /home/jiyanshusingh1/trading-engine
  sudo docker compose down --timeout 30
  sudo docker compose build
  sudo docker compose up -d
"
```

Or use the automated script:
```bash
bash scripts/deploy_gcp.sh
```

## Volume

All containers share `trading_data` → `/app/data`. The key state file is `paper_portfolio.json`.
