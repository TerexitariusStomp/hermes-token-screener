# Hermes Token Screener Dashboard

Multi-chain token screening and smart money tracking dashboard.

## Live Dashboard

The dashboard is available at: **https://hermes-token-screener.onrender.com**

## Features

- Multi-chain token discovery and screening
- Smart money wallet tracking
- Real-time token scoring with conservative methodology
- Duplicate name filtering per blockchain
- FDV/volume analysis with strong fundamentals bonuses

## Deployment

### Render.com (Recommended)

1. Fork this repository
2. Go to [Render.com](https://render.com)
3. Create a new Web Service
4. Connect your forked repository
5. Render will automatically detect the `render.yaml` configuration
6. Deploy!

### Docker

```bash
# Build the Docker image
docker build -t hermes-token-screener .

# Run the container
docker run -p 8080:8080 hermes-token-screener
```

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the dashboard
uvicorn hermes_screener.dashboard.app:app --reload --host 0.0.0.0 --port 8080
```

## API Endpoints

- `GET /` - Main dashboard
- `GET /wallets` - Wallet tracking
- `GET /token/{address}` - Token detail page
- `GET /wallet/{address}` - Wallet detail page
- `GET /health` - Health check
- `GET /api/top100` - Top 100 tokens API
- `GET /api/wallets` - Wallets API

## Data Sources

- Dexscreener (token data)
- GMGN (smart money data)
- RugCheck (security data)
- Helius (Solana data)
- Birdeye (market data)

## Scoring Methodology

The token scoring uses a conservative methodology that prioritizes:

1. **Strong fundamentals**: High FDV, holder count, liquidity
2. **Reduced penalties**: For tokens with strong fundamentals
3. **Duplicate filtering**: Only top-scoring token per symbol/chain
4. **Security checks**: Rug pull detection, honeypot detection

## License

MIT License
