# GCP Trading Engine — Access Reference

**Project**: `project-7b13e461-f96b-4c6f-84e`
**Instance**: `trading-engine` (`e2-medium`, `35.200.195.152`, zone `asia-south1-a`)
**Setup**: 3 Docker containers running under root on the host

---

## Auth (one-time on a new machine)

```bash
gcloud auth login
gcloud config set project project-7b13e461-f96b-4c6f-84e
```

## SSH into the VM

Direct SSH (port 22) is blocked by firewall from outside GCP. Use **IAP tunnel**:

```bash
gcloud compute ssh trading-engine --zone asia-south1-a --tunnel-through-iap
```

## List running containers

```bash
sudo docker ps
```

| Container Name                        | Image               | Service                              |
|---------------------------------------|---------------------|--------------------------------------|
| `trading-engine-paper-trader-1`       | `trading-engine:latest` | paper trader (paper_trade.py)    |
| `trading-engine-scanner-1`            | `trading-engine:latest` | scanner (market_scan.py --serve) |
| `trading-engine-refresher-1`          | `trading-engine:latest` | refresher (refresh_data_cache.py) |

## Common tasks

### Read the paper portfolio state

```bash
sudo docker exec trading-engine-paper-trader-1 cat /app/data/paper_portfolio.json
```

### View container logs (last 100 lines)

```bash
sudo docker logs trading-engine-paper-trader-1 --tail 100
sudo docker logs trading-engine-scanner-1 --tail 100
sudo docker logs trading-engine-refresher-1 --tail 100
```

### List files in the shared data volume

```bash
sudo docker exec trading-engine-paper-trader-1 ls /app/data/
```

The `trading_data` volume is mounted at `/app/data` in all containers.

### Check running processes

Inside a container:
```bash
sudo docker exec trading-engine-paper-trader-1 sh -c 'ps aux'
```

### Restart a service

```bash
sudo docker compose restart trading-engine-paper-trader-1
sudo docker compose restart scanner
sudo docker compose restart refresher
```

### Check how a container was started (flags / Cmd)

```bash
sudo docker inspect trading-engine-paper-trader-1 --format='{{.Config.Cmd}}'
```

### Quick trade check (per-strategy cash + recent trades)

```bash
sudo docker exec trading-engine-paper-trader-1 python3 -c "
import json
d = json.load(open('/app/data/paper_portfolio.json'))
for k, v in d.get('strategies', {}).items():
    print(f'  {k:35s} cash=₹{v.get(\"cash\",0):>8,.0f}  entries={v.get(\"day_entries\",0)}')
trades = d.get('trades', [])
print(f'  Total trades: {len(trades)}  Last 5:')
for t in trades[-5:]:
    print(f'    {t.get(\"ts\",\"\")}  {t.get(\"symbol\",\"\"):12s}  {t.get(\"side\",\"\"):6s}  PnL={t.get(\"pnl_net\",0):>+8,.0f}')
print(f'  Equity: {d.get(\"equity\",[])}')
"
```

### View all three logs simultaneously

```bash
sudo docker logs trading-engine-paper-trader-1 --tail 50
sudo docker logs trading-engine-scanner-1 --tail 50
sudo docker logs trading-engine-refresher-1 --tail 50
```

## Deploy changes to GCP

After modifying source files locally, deploy to GCP with:

```bash
# 1. SCP changed files to VM (use --tunnel-through-iap — port 22 is blocked)
#    The remote directory is owned by jiyanshusingh1, so scp to /tmp then sudo mv:
gcloud compute scp scripts/paper_trade.py trading-engine:/tmp/paper_trade.py --zone asia-south1-a --tunnel-through-iap
gcloud compute scp scripts/start_all.sh trading-engine:/tmp/start_all.sh --zone asia-south1-a --tunnel-through-iap
gcloud compute scp docker-compose.yml trading-engine:/tmp/docker-compose.yml --zone asia-south1-a --tunnel-through-iap

gcloud compute ssh trading-engine --zone asia-south1-a --tunnel-through-iap --command "
  sudo cp /tmp/paper_trade.py /home/jiyanshusingh1/trading-engine/scripts/paper_trade.py
  sudo cp /tmp/start_all.sh /home/jiyanshusingh1/trading-engine/scripts/start_all.sh
  sudo cp /tmp/docker-compose.yml /home/jiyanshusingh1/trading-engine/docker-compose.yml
  sudo chown jiyanshusingh1:jiyanshusingh1 /home/jiyanshusingh1/trading-engine/scripts/paper_trade.py
  sudo chown jiyanshusingh1:jiyanshusingh1 /home/jiyanshusingh1/trading-engine/scripts/start_all.sh
  sudo chown jiyanshusingh1:jiyanshusingh1 /home/jiyanshusingh1/trading-engine/docker-compose.yml
"

# 2. SSH, rebuild image, restart containers
gcloud compute ssh trading-engine --zone asia-south1-a --tunnel-through-iap --command "
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

## .env file

The `.env` file is in `.gitignore` and must be deployed separately. It needs the IAP tunnel too:

```bash
gcloud compute scp .env trading-engine:/tmp/.env --zone asia-south1-a --tunnel-through-iap
gcloud compute ssh trading-engine --zone asia-south1-a --tunnel-through-iap --command "
  sudo cp /tmp/.env /home/jiyanshusingh1/trading-engine/.env
  sudo chown jiyanshusingh1:jiyanshusingh1 /home/jiyanshusingh1/trading-engine/.env
"
```

## Volume

All containers share `trading_data` → `/app/data`. The key state file is `paper_portfolio.json`.
