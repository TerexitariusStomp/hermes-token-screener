# Hermes Token Screener

Multi-source token enrichment pipeline + wallet tracker + Telegram contract scraper.

## Architecture

```
Telegram Chats ──► telegram_scraper.py ──► central_contracts.db
                                                   │
                                                   ▼
                                           token_enricher.py
                                     (12 layers, resilient try/bypass)
                                                   │
                                                   ▼
                                          scored top 100 tokens
                                                   │
                                                   ▼
                                           wallet_tracker.py
                                     (discovery + scoring + detection)
                                                   │
                                                   ▼
                                     ranked smart money wallets
```

## Scripts (Active Pipeline)

| Script | Cron | Purpose |
|--------|------|---------|
| `token_enricher.py` | `10 * * * *` | 12-layer token enrichment + scoring |
| `wallet_tracker.py` | `15 * * * *` | Wallet discovery, scoring, pattern detection |
| `telegram_scraper.py` | `*/10 * * * *` | Telegram contract address gathering |

## Token Enrichment (12 Layers)

| Layer | Source | Data |
|-------|--------|------|
| 0 | Dexscreener | Volume, txns, FDV, liquidity, price [REQUIRED] |
| 1 | Surf | Social sentiment, mindshare, trending |
| 2 | GoPlus v2 | EVM security (honeypot, tax, mint) |
| 3 | RugCheck | Solana security (rug score, insiders) |
| 4 | Etherscan | Contract verification |
| 5 | De.Fi | Security analysis, holder concentration |
| 6 | Derived | Computed signals (no API) |
| 7 | CoinGecko | Market data, exchange listings |
| 8 | GMGN | Dev conviction, smart money, bot detection |
| 9 | Social | Telegram DB + composite social score |
| 10 | Zerion | Price, market cap, FDV, supply, verified flag |
| 11 | CoinStats | Risk score, liquidity score, volatility |

## Token Scoring

Base 0-100 from: social momentum (0-35), freshness (0-15), low FDV (0-15), volume (0-20), txns (0-15), price momentum (0-10).

**Steep decline penalties:**
- h1 < -60%: score ×0.1 (rug in progress)
- h6 < -50%: score ×0.2 (crashed)
- h6 < -30%: score ×0.5 (declining)
- Death spiral (vol dying + declining): ×0.3

## Wallet Scoring (0-100)

| Factor | Points | Description |
|--------|--------|-------------|
| Realized PNL | 0-35 | Profit TAKEN (not paper gains) |
| Trade Count | 0-20 | Active wallets = established traders |
| Win Rate | 0-10 | Profitable tokens / total tokens |
| ROI | 0-10 | Average profit_change per token |
| Entry Timing | 0-8 | Earlier = better |
| Wallet Age | 0-5 | Longer = more established |
| Smart Tag | 0-5 | TOP1, KOL, SMART = better |
| Insider Bonus | 0-5 | MORE insider flags = BETTER |
| DeFi/Portfolio | 0-5 | Staked/borrowed = serious player |
| Social | 0-2 | Linked Twitter = credibility |

**Penalties:**
- Round trips (profit without selling): -15 each
- Copy trade: -20
- Rug history: -100 each (disqualifier)

## Pattern Detection

| Pattern | Description |
|---------|-------------|
| SNIPER | Exits quickly, high sell ratio |
| SWING | Moderate holds, partial exits |
| HOLDER | Few sells, long holds |
| DEGEN | >50 trades across >10 tokens |
| INSIDER | Flagged by heuristics |
| ACTIVE | >20 trades |

## API Keys (in `~/.hermes/.env`)

```
DEFI_API_KEY=
ETHERSCAN_API_KEY=
COINGECKO_API_KEY=
GMGN_API_KEY=
SURF_API_KEY=
RUGCHECK_API_KEY=
ZERION_API_KEY=
COINSTATS_API_KEY=
HELIUS_API_KEY=
ALCHEMY_API_KEY=
QUICKNODE_KEY=
TG_API_ID=
TG_API_HASH=
```

## Legacy Scripts (still in repo, used by smart_money_research.py)

- `smart_money_research.py` — older enrichment pipeline
- `dexscreener_enricher.py`, `goplus_enricher.py`, etc. — individual enrichers (superseded by token_enricher.py)
- `telegram_ingestor.py` — Telegram session handler
- `wallet_discovery.py` — older wallet finder
- `pattern_learner.py`, `central_db_sink.py` — ML pattern matching
