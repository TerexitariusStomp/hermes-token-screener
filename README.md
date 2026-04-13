# Hermes Token Screener

Multi-source token screening pipeline that aggregates data from 10+ providers to score and rank tokens for buy signals.

## Architecture

```
Telegram Chats ──► Contract Scraper ──► central_contracts.db
                                              │
                                              ▼
                                        Token Screener
                                    ┌─────────┼─────────┐
                                    ▼         ▼         ▼
                              Dexscreener  GoPlus   CoinGecko
                              RugCheck     De.Fi    Etherscan
                              GMGN         Surf     Derived
                              Social (Telegram DB + CoinGecko)
                                              │
                                              ▼
                                    Scored Token List (top 100)
                                              │
                                              ▼
                                    Wallet Tracker ──► Alert
```

## Data Sources

| Provider | Data | Chain Support |
|----------|------|---------------|
| Dexscreener | Volume, txns, price, liquidity, age | All |
| RugCheck | Rug score, insiders, holder concentration, LP locks | Solana |
| GMGN | Dev conviction, bot detection, smart wallets, renounced | Sol/BSC/Base |
| GoPlus | Honeypot, tax, mintable, holders | EVM |
| De.Fi | Security issues, scammed, holders | ETH/BSC/Solana/Base |
| CoinGecko | Sentiment, ATH, exchange listings, categories | All |
| Etherscan | Contract verification, compiler, proxy | EVM |
| Surf | Fear & Greed, social sentiment, mindshare, trending | Market-wide |
| Solana RPC | Mint authority, holder concentration | Solana |
| Telegram DB | Channel count, mention velocity, viral detection | N/A |

## Setup

```bash
# Install dependencies
pip install requests python-dotenv telethon

# Copy environment file
cp .env.example .env
# Fill in your API keys in .env

# Run the screener
python scripts/token_screener.py

# Run the contract scraper
python scripts/telegram_contract_scraper.py
```

## Scoring

Tokens are scored 0-100 based on:
- **Cross-channel calls + social momentum** (0-35 pts)
- **Freshness** (0-15 pts)
- **Low FDV** (0-15 pts)
- **Volume** (0-20 pts)
- **Transaction activity + buy ratio** (0-15 pts)
- **Price momentum** (0-10 pts)

Security penalties (GoPlus, RugCheck, De.Fi, GMGN, Etherscan) can reduce scores to 0 for honeypots, rugs, or critical issues.

## Wallet Tracking

Top wallets from winning tokens are tracked via:
- **Alchemy/QuickNode webhooks** (EVM chains)
- **Helius webhooks** (Solana)

When a tracked wallet transfers to a new token, an alert is generated.

## Files

```
scripts/
  token_screener.py          # Main scoring pipeline
  telegram_contract_scraper.py  # Telegram chat scraper
  address_extractor.py       # EVM/Solana address extraction
  smart_money_config.py      # Channel configuration
enrichers/
  dexscreener_enricher.py    # DEX data
  rugcheck_enricher.py       # Solana security
  gmgn_enricher_v2.py        # Dev conviction, bot detection
  goplus_enricher.py         # EVM security
  defi_enricher.py           # Contract analysis
  coingecko_enricher.py      # Market data, sentiment
  etherscan_enricher.py      # Contract verification
  surf_enricher.py           # Market context, social
  derived_security.py        # Computed signals (fallback)
  social_enricher.py         # Telegram + CoinGecko social
```

## License

MIT
