# Hermes Token Screener Dashboard

Multi-chain token screening and smart money tracking dashboard with automatic HTTPS deployment.

## 🚀 Quick Start

### Option 1: One-Command Deployment (Recommended)

```bash
# Clone the repository
git clone https://github.com/TerexitariusStomp/hermes-token-screener.git
cd hermes-token-screener

# Run quick start (installs Docker if needed)
sudo ./quickstart.sh
```

### Option 2: Manual Deployment

```bash
# Clone the repository
git clone https://github.com/TerexitariusStomp/hermes-token-screener.git
cd hermes-token-screener

# Deploy with Docker Compose
./deploy.sh
```

### Option 3: Docker Compose Only

```bash
# Clone and deploy
git clone https://github.com/TerexitariusStomp/hermes-token-screener.git
cd hermes-token-screener

# Create directories
mkdir -p data logs caddy-data caddy-config nginx-data

# Start services
docker-compose up -d
```

## 🌐 Access Your Dashboard

After deployment, your dashboard will be available at:

- **HTTP**: `http://YOUR_SERVER_IP`
- **HTTPS**: `https://YOUR_SERVER_IP` (if domain configured)

### Default URLs:
- **Dashboard**: `http://YOUR_SERVER_IP/`
- **Wallets**: `http://YOUR_SERVER_IP/wallets`
- **Token Detail**: `http://YOUR_SERVER_IP/token/{address}`
- **API**: `http://YOUR_SERVER_IP/api/top100`
- **Health Check**: `http://YOUR_SERVER_IP/health`

## 📡 Data Sources

The screener uses these **non-Telegram** data sources — no Telegram account required:

| Source | Script | Contracts | Description |
|--------|--------|-----------|-------------|
| **DexScreener** | `dexscreener_discovery.py` | 9,106+ | Boosted + profiled tokens across chains |
| **PumpPortal** | `pumpportal_harvester.py` | 1,563+ | Real-time Solana token launches |
| **GMGN Trenches** | `gmgn_harvester.py` | 119+ | Trending Solana tokens |

### Optional: Telegram Channels

Telegram call channels provide supplementary alpha signals but require manual joining.
See [RECOMMENDED_CHANNELS.md](RECOMMENDED_CHANNELS.md) for curated channel recommendations.
The `telegram_scraper.py` script is archived due to Telegram account restrictions.

## 🏗️ Architecture

### Components:
1. **Hermes Dashboard** (FastAPI): Backend API and web interface
2. **Caddy**: Reverse proxy with automatic HTTPS (Let's Encrypt)
3. **Nginx**: Alternative reverse proxy (optional)
4. **Docker Compose**: Container orchestration

### Data Flow:
```
DexScreener API ─┐
PumpPortal WS ───┼─→ Token DB → FastAPI Dashboard → Caddy → User
GMGN API ────────┘
```

## ⚙️ Configuration

### Environment Variables (.env file):
```bash
# Domain configuration (for HTTPS)
DOMAIN=hermes-token-screener.com
EMAIL=hermeticsintellegencia@proton.me

# Application settings
PORT=8080
HERMES_HOME=/app
PYTHONPATH=/app
```

### Custom Domain Setup:
1. Point your domain to your server IP
2. Update `.env` file with your domain:
   ```bash
   DOMAIN=your-domain.com
   EMAIL=your-email@example.com
   ```
3. Restart services:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

## 🔧 Management

### View Logs:
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f hermes-dashboard
docker-compose logs -f caddy
```

### Stop Services:
```bash
docker-compose down
```

### Restart Services:
```bash
docker-compose restart
```

### Update Application:
```bash
git pull
docker-compose build
docker-compose up -d
```

## 📊 API Endpoints

### Main Endpoints:
- `GET /` - Main dashboard
- `GET /wallets` - Wallet tracking
- `GET /token/{address}` - Token detail page
- `GET /wallet/{address}` - Wallet detail page
- `GET /health` - Health check
- `GET /api/top100` - Top 100 tokens API
- `GET /api/wallets` - Wallets API

### Example API Call:
```bash
# Get top 100 tokens
curl http://YOUR_SERVER_IP/api/top100

# Get wallets
curl http://YOUR_SERVER_IP/api/wallets?min_score=50
```

## 🐳 Docker Details

### Docker Compose Services:
1. **hermes-dashboard**: FastAPI application
2. **caddy**: Reverse proxy with automatic HTTPS
3. **nginx**: Alternative reverse proxy (optional)

### Volumes:
- `./data` → `/app/.hermes/data` (token data)
- `./logs` → `/app/.hermes/logs` (application logs)
- `./caddy-data` → `/data` (Caddy certificates)
- `./caddy-config` → `/config` (Caddy configuration)

### Ports:
- **80**: HTTP (Caddy)
- **443**: HTTPS (Caddy)
- **8080**: Direct FastAPI access (optional)

## 🔒 Security Features

### Automatic HTTPS:
- Let's Encrypt certificates
- Automatic certificate renewal
- HTTP to HTTPS redirect

### Security Headers:
- HSTS (Strict-Transport-Security)
- X-Frame-Options: DENY
- X-Content-Type-Options: nosniff
- X-XSS-Protection: 1; mode=block
- Referrer-Policy: strict-origin-when-cross-origin

### Rate Limiting:
- API: 10 requests/second
- Burst: 20 requests

## 🛠️ Troubleshooting

### Port 80 Already in Use:
```bash
# Check what's using port 80
sudo netstat -tlnp | grep :80

# Stop conflicting service
sudo systemctl stop apache2  # or nginx
```

### Permission Denied:
```bash
# Make scripts executable
chmod +x deploy.sh quickstart.sh

# Run with sudo
sudo ./deploy.sh
```

### Docker Not Running:
```bash
# Start Docker
sudo systemctl start docker

# Enable Docker on boot
sudo systemctl enable docker
```

### View Container Status:
```bash
docker-compose ps
docker stats
```

## 📈 Monitoring

### Health Checks:
- Application: `http://localhost:8080/health`
- Caddy: Automatic health monitoring
- Docker: Built-in health checks

### Logs:
- Application logs: `./logs/`
- Caddy logs: `./caddy-data/logs/`
- Docker logs: `docker-compose logs`

## 🔄 Updates

### Automatic Updates:
The dashboard automatically updates with new token data from the enrichment pipeline.

### Manual Updates:
```bash
# Pull latest changes
git pull

# Rebuild and restart
docker-compose build
docker-compose up -d
```

## 📝 License

MIT License - See LICENSE file for details.

## 🆘 Support

For issues or questions:
- GitHub Issues: https://github.com/TerexitariusStomp/hermes-token-screener/issues
- Email: hermeticsintellegencia@proton.me
- Telegram: @terexserverbot
