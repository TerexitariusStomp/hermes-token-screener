---
name: smart-money-feedback-loop
description: "Smart money purchase monitoring and feedback loop: wallet→token→wallet discovery cycle with enrichment and prioritization"
category: trading
created: 2026-04-17
triggers:
  - "smart money tracking"
  - "wallet purchase monitor"
  - "copy trading discovery"
  - "smart money feedback loop"
---

# Smart Money Feedback Loop

Continuous cycle: Top Wallets → Monitor Purchases → Enrich Tokens → Score → Discover New Wallets → repeat

## Architecture

```
GMGN SmartMoney API (every 30min)
    ↓
smart_money_monitor.py polls sol/base/bsc
    ↓
smart_money_purchases table (individual buys)
smart_money_tokens table (per-token summary: buyer_count, total_usd, avg_usd, top_buyer_score)
    ↓
central_contracts.db (auto-inserted for enrichment pipeline pickup)
    ↓
token_enricher.py picks up (min_channels=1)
    ↓
Dexscreener + GoPlus + Goldsky + Goldrush enrichment
    ↓
Scored tokens → top100_phase4_social.json
    ↓
wallet_tracker.py discovers new wallets from token holders
    ↓
Cross-scoring re-ranks wallets by token portfolio quality
    ↓
Best wallets → track their future buys → repeat
```

## Key Files

- `scripts/smart_money_monitor.py` — Polls GMGN, logs purchases, inserts tokens for enrichment
- `hermes_screener/async_enrichment.py` — Enrichment pipeline (16 layers)
- `scripts/wallet_tracker.py` — Discovers wallets from token holders via GMGN
- `scripts/cross_scoring.py` — Re-scores tokens/wallets in feedback loop
- `scripts/export_github_pages.py` — `export_smart_money()` exports enriched SM data

## Database Schema

**smart_money_purchases** (in wallet_tracker.db):
- tx_hash (UNIQUE with token_address), wallet_address, chain, token_address, token_symbol
- side (buy/sell), amount_usd, price_usd, timestamp
- wallet_score, wallet_tags, enriched (0/1), score

**smart_money_tokens** (in wallet_tracker.db):
- token_address + chain (PRIMARY KEY)
- buyer_count, total_buy_usd, avg_buy_usd, top_buyer_score
- discovery_wallets (JSON array of wallet addresses)
- enriched (0/1), score

## Enrichment Pipeline Chain Correction (CRITICAL)

Problem: Dexscreener API was overwriting correct chain labels from GMGN with `chainId` from Dexscreener response. BSC tokens got relabeled as "ethereum" because Dexscreener found the same address on Ethereum.

Fix in `async_enrichment.py` line ~157:
```python
# Only correct chain from Dexscreener when original is unreliable.
# GMGN/GMGN-trenches sources already know their chain.
# Telegram scraper defaults 0x addresses to 'ethereum' which may be wrong.
ds_chain = best.get("chainId", "")
orig_chain = token.get("chain", "")
reliable_sources = {"gmgn_trenches", "gmgn_trending"}
is_reliable = any(
    (token.get("last_source", "") or "").startswith(s)
    for s in reliable_sources
)
if ds_chain and ds_chain != orig_chain and not is_reliable:
    token["chain"] = ds_chain
```

## API Integrations

**GMGN** (gmgn-cli): `track smartmoney --chain sol/base/bsc --limit 100 --raw`
- Returns: transaction_hash, maker (wallet), base_address (token), side, amount_usd, price_usd
- Polls every 30min via cron

**Goldsky Edge RPC** (Layer 15): `edge.goldsky.com/standard/evm/{chain_id}?secret={key}`
- Gets recent Transfer events, counts unique senders/receivers
- Supports all EVM chains (just change chain_id)

**Goldrush/Covalent** (Layer 14): `api.covalenthq.com/v1/{chain_id}/tokens/{addr}/token_holders/`
- Token holder count + top 5 holders
- 57 EVM chains supported

**Bitquery** (Layer 16, point-optimized):
- Real-time DB only (5 pts/query), never streaming (40 pts/min)
- 1-hour cache TTL, circuit breaker on 402, LIMIT 10, concurrency=1

## Cron Jobs

- `smart-money-purchase-monitor` — every 30min, polls GMGN + runs enricher
- `dexscreener-evm-discovery` — every 3h, Dexscreener boosted + profiles
- `gmgn-harvester` — every 15min, multi-chain trenches + trending

## Frontend Pages

- `smart-money.html` — Enriched SM tokens ranked by buyer_count × score × (1+total_usd/1000)
- `smart-money-wallets.html` — Wallets trading SM tokens, ranked by score × sm_tokens_held
- `smart-money-feed.html` — Live purchase feed with chain/token/min-USD filters

## Prioritization

**SM Tokens**: `buyer_count × score × (1 + total_buy_usd / 1000)` — rewards tokens bought by many smart wallets with high scores and large positions

**SM Wallets**: `wallet_score × max(1, sm_tokens_held)` — rewards high-quality wallets that are actively trading SM tokens

## Export Pipeline Fixes (Apr 17, 2026)

### Dex sub-object flattening (CRITICAL)
Enricher stores data under `dex` sub-object. Frontend expects top-level fields:
```python
# In export_tokens() — add after normalizing chains:
dex = token.get("dex", {})
if dex:
    token["fdv"] = token.get("fdv") or dex.get("fdv") or dex.get("market_cap") or 0
    token["symbol"] = token.get("symbol") or dex.get("symbol") or ""
    token["volume_h24"] = dex.get("volume_h24", 0) or 0
    token["volume_h1"] = dex.get("volume_h1", 0) or 0
    token["price_change_h1"] = dex.get("price_change_h1")
    token["price_change_h6"] = dex.get("price_change_h6")
    token["age_hours"] = dex.get("age_hours")
```

### Pick enriched file with MOST tokens (not first match)
```python
# BAD: picks first file that exists (might have 2 tokens)
for src in [top100_phase4_social.json, ...]:
    if src.exists(): enriched_lookup = ...; break

# GOOD: picks file with most enriched tokens
best_count = 0
for src in [top100.json, top100_phase4_social.json, ...]:
    candidate = {addr: t for t in tokens}
    if len(candidate) > best_count:
        enriched_lookup = candidate
        best_count = len(candidate)
```

### SM wallets from smart_money_purchases (NOT wallet_token_entries)
SM tokens are discovered by GMGN monitor, not wallet tracker. Use:
```sql
SELECT p.wallet_address, p.chain, MAX(p.wallet_score), 
       COUNT(DISTINCT p.token_address), GROUP_CONCAT(DISTINCT p.token_symbol)
FROM smart_money_purchases p WHERE p.side = 'buy'
GROUP BY p.wallet_address
```

### Dexscreener URL generation for SM tokens
```python
"dex_url": enriched.get("dex_url", "") or f"https://dexscreener.com/{chain.lower()}/{addr}"
```

### SM Feed time display
Use actual datetime, NOT relative time:
```javascript
function fmt_date(ts){
  if(!ts)return"—";
  const d=new Date(ts*1000);
  return d.toISOString().slice(0,16).replace("T"," ");
}
```

## Scoring Improvements (Apr 17, 2026)

### Zero volume penalty
```python
if vol_h24 <= 0:
    score -= 20
    negatives.append("no volume")
    # Exception: very fresh tokens (< 2h) with FDV
    if fdv > 0 and age_hours is not None and age_hours < 2:
        score += 3
```

### Stale data penalty
```python
if pc_h1 is None and pc_h6 is None and pc_h24 is None:
    score *= 0.3
    negatives.append("stale data")
```

### Bonding curve detection
```python
dex_name = (dex.get("dex") or "").lower()
liq = dex.get("liquidity_usd") or 0
on_bonding_curve = False

if dex_name in ("pumpfun", "pump.fun"):
    on_bonding_curve = True
elif fdv > 0 and liq > 0 and age_hours is not None and age_hours < 24:
    if liq / fdv < 0.02:  # Less than 2% liquidity ratio
        on_bonding_curve = True

if on_bonding_curve:
    score *= 0.5
    negatives.append("on bonding curve")
```

## Symbol Blocklist (Apr 17, 2026)

Fiat/stablecoins and native tokens are NOT tradeable tokens. Block them from scoring:
```python
BLOCKED_SYMBOLS = {
    "usd", "usdt", "usdc", "dai", "busd", "tusd", "eur", "gbp",
    "jpy", "cny", "btc", "eth", "sol", "bnb", "xrp", "wsol",
    "weth", "wbtc", "steth", "cbeth", "sui", "matic",
}
symbol = (dex.get("symbol") or token.get("symbol") or "").lower().strip()
if symbol in BLOCKED_SYMBOLS:
    return 0, [], [f"BLOCKED: {symbol.upper()} is not a tradeable token"]
```

Also add to trending_keywords.py STOPWORDS to prevent keyword extraction.

## XRPL Address Detection (Apr 17, 2026)

XRPL addresses start with 'r' and are 25-35 characters. Add to telegram_scraper.py:
```python
XRPL_PATTERN = re.compile(r"r[1-9A-HJ-NP-Za-km-z]{24,34}")

# In extract_addresses():
for match in XRPL_PATTERN.findall(text):
    if match not in seen:
        results.append((match, match, "xrpl_raw"))
        seen.add(match)

# In scrape_messages() chain detection:
chain = (
    "solana" if not normalized.startswith("0x") and not normalized.startswith("r")
    else "xrpl" if normalized.startswith("r")
    else "ethereum"
)
```

## Pitfalls

- GMGN smartmoney API returns ALL smart money trades, not just our tracked wallets — use for token discovery
- `min_channels` must be 1 for SM tokens to qualify for enrichment (they have channel_count=1)
- Chain names: GMGN uses "sol"/"base"/"bsc", Telegram scraper uses "solana"/"ethereum" — normalize via CHAIN_MAP in export
- SM wallet count grows slowly — enrichment must run first, then wallets are discovered from enriched token holders
- Export prints per-row in loop if not careful — move print after loop
- Dex fields are nested, must flatten to top level or frontend shows "undefined" / 0 values
- USD was accidentally appearing in top tokens — add BLOCKED_SYMBOLS to prevent
- Pump.fun tokens have bonding curve that needs graduation to PumpSwap for real liquidity
## Related Skills
`token-screener`, `wallet-tracker`
