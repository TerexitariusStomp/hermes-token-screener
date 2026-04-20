# Hermes Remote Worker

Lightweight FastAPI service that offloads all internet-dependent operations
from the local hermes daemon to a free cloud VPS.

## What it does

- **Token enrichment** - Dexscreener, GoPlus, RugCheck, Etherscan, CoinGecko
- **Generic API proxy** - forward any HTTP request to avoid local IP rate limits
- **Health monitoring** - `/health` endpoint for uptime checks

## Free VPS Options

### Oracle Cloud Free Tier (recommended)
- 4 ARM cores, 24GB RAM, 200GB storage
- Sign up: https://www.oracle.com/cloud/free/
- Region: US or EU (always-free eligible)
- Deploy via SSH after creating instance

### Render (easiest)
- Free tier: 750 hrs/mo, auto-sleep after 15min inactivity
- Push to GitHub → connect Render → auto-deploy
- Tradeoff: cold starts (30-60s)

### Fly.io
- Free tier: 3 shared-1x VMs, 160GB bandwidth
- `fly deploy` after `fly launch`

### Railway
- $5/mo credit, ~500 hrs free tier
- Push to GitHub → connect Railway → auto-deploy

## Deployment

### Option A: Oracle Cloud Free Tier (best performance)

1. Create Ubuntu ARM instance (always-free eligible)
2. SSH into instance:
   ```bash
   sudo apt update && sudo apt install -y docker.io
   sudo usermod -aG docker $USER
   ```
3. Clone and deploy:
   ```bash
   git clone https://github.com/YOUR_USER/hermes-token-screener.git
   cd hermes-token-screener/worker
   docker build -t hermes-worker .
   docker run -d --name hermes-worker \
     -p 10000:10000 \
     -e ETHERSCAN_API_KEY=your_key \
     -e COINGECKO_API_KEY=your_key \
     -e RUGCHECK_SHIELD_KEY=your_key \
     --restart unless-stopped \
     hermes-worker
   ```
4. Note the public IP: `curl http://localhost:10000/health`

### Option B: Render (easiest, free)

1. Fork this repo on GitHub
2. Go to https://dashboard.render.com → New Web Service
3. Connect your forked repo
4. Settings:
   - Root Directory: `worker`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app:app --host 0.0.0.0 --port 10000`
   - Instance Type: Free
5. Add environment variables in Render dashboard
6. Deploy! Note the URL: `https://your-app.onrender.com`

### Option C: Fly.io

1. Install flyctl: `curl -L https://fly.io/install.sh | sh`
2. In worker directory: `fly launch`
3. Set secrets: `fly secrets set ETHERSCAN_API_KEY=your_key`
4. Deploy: `fly deploy`

## Configure Local Daemon

After deploying, set the worker URL in your `.env`:

```bash
HERMES_WORKER_URL=https://your-app.onrender.com   # or http://YOUR_VPS_IP:10000
```

The local daemon will automatically delegate all API calls to the remote worker.

## API Endpoints

### `POST /enrich`
Enrich tokens with market/security data.

```json
{
  "tokens": [
    {"chain": "base", "address": "0x...", "symbol": "TOKEN"}
  ],
  "layers": ["dexscreener", "goplus", "rugcheck", "etherscan", "coingecko"]
}
```

Response:
```json
{
  "tokens": [{
    "chain": "base",
    "address": "0x...",
    "symbol": "TOKEN",
    "price_usd": "1.23",
    "fdv": 12300000,
    "volume_h24": 500000,
    "goplus_is_honeypot": false,
    "rugcheck_score": 150,
    "etherscan_verified": true,
    "score": 45.5,
    "positives": ["med_vol_$500K", "rugcheck_safe"],
    "negatives": []
  }],
  "layer_status": {...},
  "total_elapsed": 3.45
}
```

### `POST /proxy`
Proxy any HTTP request.

```json
{
  "url": "https://api.dexscreener.com/tokens/v1/base/0x...",
  "method": "GET",
  "headers": {"Authorization": "Bearer ..."}
}
```

### `GET /health`
Health check.

```json
{"status": "healthy", "timestamp": 1745000000, "uptime": 3600.5}
```

## Local Development

```bash
cd worker
pip install -r requirements.txt
uvicorn app:app --reload --port 10000
curl http://localhost:10000/health
```

## Architecture

```
┌──────────────────┐     ┌──────────────────┐
│   Local Daemon   │     │   Remote Worker   │
│  (hermes core)   │────▶│  (free VPS/cloud) │
│                  │ HTTP │                   │
│  - Scheduling    │     │  - Dexscreener    │
│  - Database      │     │  - GoPlus         │
│  - Monitoring    │     │  - RugCheck       │
│  - AI Brain      │     │  - Etherscan      │
│  - Telegram      │     │  - CoinGecko      │
└──────────────────┘     └──────────────────┘
```

All internet-facing API calls happen on the remote VPS.
The local daemon handles scheduling, database, and business logic.
