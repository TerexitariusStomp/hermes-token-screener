# Local Development Deployment

This guide covers running the Hermes Token Screener on a **local machine** (macOS, Linux, or Windows) without Docker — useful for development, testing, or self-hosted setups without a server.

---

## Prerequisites

- **Python 3.10–3.12** (check with `python --version`)
- **pip** (`pip --version`)
- **Git**
- Network access for API calls (DexScreener, PumpPortal, GMGN, etc.)

---

## 1. Clone the Repository

```bash
git clone https://github.com/TerexitariusStomp/hermes-token-screener.git
cd hermes-token-screener
```

---

## 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### ⚠️ Common Issues

**`structlog` version conflict:**
`structlog 24.x` is no longer published on PyPI. If you get an error like `No matching distribution found for structlog==24.x`, your `requirements.txt` has an upper bound that's too low. The fix is already in this repo's `requirements.txt`:

```
structlog>=23.0.0,<26.0.0
```

If you're working from an older checkout, edit `requirements.txt` and change:
```diff
- structlog>=23.0.0
+ structlog>=23.0.0,<26.0.0
```

---

## 3. Create Required Data Directories

```bash
mkdir -p data/token_screener data/logs
```

The dashboard reads and writes token data to `data/token_screener/top100.json`. You can start with an empty file:

```bash
echo '{ "tokens": [], "generated_at_iso": "Never", "total_candidates": 0 }' > data/token_screener/top100.json
```

Alternatively, you can copy existing data from a production deployment:
```bash
# On the server where Hermes is running:
cp ~/.hermes/data/token_screener/* data/token_screener/
cp ~/.hermes/data/central_contracts.db data/  # if it exists
```

---

## 4. Set Environment Variables

Two environment variables are required before running:

| Variable | Value | Purpose |
|---|---|---|
| `HERMES_HOME` | `<repo-root>` | Points to the repository root — used for all data/log paths |
| `PYTHONPATH` | `<repo-root>` | Must include the repo root so `scripts/` is found for imports |

### Linux/macOS

```bash
export HERMES_HOME="$(pwd)"
export PYTHONPATH="$(pwd)"
```

### Windows (PowerShell)

```powershell
$env:HERMES_HOME = "C:\path\to\hermes-token-screener"
$env:PYTHONPATH = "C:\path\to\hermes-token-screener"
```

> **Note:** `HERMES_HOME` must be the **repository root** (where `hermes_screener/`, `scripts/`, `data/`, and `Dockerfile` live) — NOT the `hermes_screener/` subdirectory.

---

## 5. Run the Dashboard

```bash
python -m uvicorn hermes_screener.dashboard.app:app --host 127.0.0.1 --port 8280
```

Then open your browser at **http://127.0.0.1:8280**

### Windows (PowerShell) — Background Process

```powershell
Start-Process -FilePath python -ArgumentList "-m", "uvicorn", "hermes_screener.dashboard.app:app", "--host", "127.0.0.1", "--port", "8280" -WindowStyle Hidden
```

### Health Check

```bash
curl http://127.0.0.1:8280/health
```

Expected response:
```json
{"status":"healthy","version":"9.0.0","checks":{"top100":{"exists":true,...}}}
```

---

## 6. (Optional) Populate with Real Token Data

The dashboard starts empty. To get live token data, run the harvester scripts:

```bash
# DexScreener token discovery
python scripts/dexscreener_discovery.py

# PumpPortal (Solana new launches)
python scripts/pumpportal_harvester.py

# GMGN (trending Solana tokens)
python scripts/gmgn_harvester.py

# Token enrichment (scores, social, etc.)
python scripts/token_enricher.py

# Top-100 ranking
python scripts/enhanced_scoring.py
```

Each harvester fetches from its respective API and writes to `data/token_screener/`. The dashboard auto-refreshes every 30 seconds.

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `HERMES_HOME` | `~/.hermes` | Repository root (where data/, logs/, hermes_screener/ live) |
| `PYTHONPATH` | (none) | Must include `HERMES_HOME` so `scripts/` and `hermes_screener/` are importable |
| `PORT` | `8080` | Dashboard port (the `uvicorn --port` flag overrides this) |
| `DOMAIN` | `localhost` | Used by Caddy/Traefik for HTTPS routing |
| `CF_EMAIL` | (empty) | Cloudflare email for DNS challenges |
| `CF_API_TOKEN` | (empty) | Cloudflare API token for automatic DNS |

### All API Keys (optional — graceful degradation)

If not set, the app skips that data source quietly.

| Variable | Source |
|---|---|
| `ETHERSCAN_API_KEY` | Etherscan |
| `GMGN_API_KEY` | gmgn.ai |
| `ALCHEMY_API_KEY` | Alchemy (ETH/base/arb) |
| `HELIUS_API_KEY` | Helius (Solana) |
| `SOLSCAN_API_KEY` | Solscan |
| `BIRDEYE_API_KEY` | Birdeye |
| `ZERION_API_KEY` | Zerion (wallet portfolios) |
| `DEXSCREENER_API_KEY` | DexScreener |
| `QUICKNODE_KEY` | QuickNode RPC |

---

## Docker Deployment (Original)

The original Docker-based deployment is still fully supported:

```bash
# Linux/macOS
chmod +x deploy.sh quickstart.sh
sudo ./deploy.sh

# Or with Docker Compose directly
mkdir -p data logs caddy-data caddy-config nginx-data
docker-compose up -d
```

### Docker Environment Variables

Create a `.env` file in the repo root:

```env
HERMES_HOME=/app/hermes_screener   # inside the container this is /app/hermes_screener
PYTHONPATH=/app
PORT=8080
DOMAIN=your-domain.com             # optional, for HTTPS
EMAIL=you@example.com              # optional, for Let's Encrypt
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'token_lifecycle'`
Your `PYTHONPATH` doesn't include the repo root. The `scripts/` directory is imported by `hermes_screener/dashboard/app.py` via `sys.path.insert(0, str(settings.hermes_home / "scripts"))`.

```bash
# Fix:
export PYTHONPATH="$(pwd)"   # Linux/macOS
$env:PYTHONPATH = "$PWD"     # PowerShell
```

### `structlog` install fails — "No matching distribution"
The `requirements.txt` upper bound is wrong. Change `structlog>=23.0.0` to `structlog>=23.0.0,<26.0.0`. This repo's `requirements.txt` already has the fix.

### `HERMES_HOME` confusion
The **Docker** `Dockerfile` sets `HERMES_HOME=/app/hermes_screener` (the inner app directory inside the container). But when running **locally without Docker**, set `HERMES_HOME` to the **repository root**. These are different — the Docker container is structured differently than a local clone.

### Empty dashboard / no tokens
The dashboard shows "0 tokens" until harvesters populate `data/token_screener/top100.json`. Run the discovery scripts or copy data from an existing deployment (see Step 3 and Step 6).

### Port 8280 already in use
Change the port with `uvicorn --port <another-port>` and update your browser URL.

### Windows: `&&` not valid in PowerShell
Use `;` instead: `cd repo ; command1 ; command2`
Or use `-Command` for single commands.

---

## Quick-Start One-Liner (Linux/macOS)

```bash
git clone https://github.com/TerexitariusStomp/hermes-token-screener.git && \
  cd hermes-token-screener && \
  pip install -r requirements.txt && \
  mkdir -p data/token_screener data/logs && \
  echo '{ "tokens": [], "generated_at_iso": "Never", "total_candidates": 0 }' > data/token_screener/top100.json && \
  export HERMES_HOME="$(pwd)" && export PYTHONPATH="$(pwd)" && \
  python -m uvicorn hermes_screener.dashboard.app:app --host 127.0.0.1 --port 8280
```

Then open **http://127.0.0.1:8280**