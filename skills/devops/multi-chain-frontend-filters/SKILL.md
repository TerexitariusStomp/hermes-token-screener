---
name: multi-chain-frontend-filters
description: >
  Reusable pattern for GitHub Pages dashboards with chain filters,
  market cap filters, sortable columns, and chain-aware block explorer links.
version: 1.0
tags: [frontend, github-pages, filters, multi-chain, dashboard]
---

# Multi-Chain Frontend Filters

## Pattern: Filter Bar + Sortable Table

Every page gets: chain dropdown, market cap dropdown, filter count, sortable columns.

### HTML Structure
```html
<div class="filters">
  <label>Chain <select id="filter-chain"><option value="">All Chains</option></select></label>
  <label>Market Cap <select id="filter-mcap">
    <option value="">All</option>
    <option value="< $50K">&lt; $50K</option>
    <option value="$50K - $250K">$50K - $250K</option>
    <option value="$250K - $1M">$250K - $1M</option>
    <option value="$1M - $10M">$1M - $10M</option>
    <option value="$10M - $100M">$10M - $100M</option>
    <option value="$100M+">$100M+</option>
  </select></label>
  <span class="filter-count" id="filter-count"></span>
</div>
```

### Sortable Column Headers
```html
<th data-sort="score">Score <span class="sort-arrow"></span></th>
```

### CSS (add to style.css)
```css
.filters{display:flex;gap:1rem;align-items:center;flex-wrap:wrap;margin-bottom:1rem}
.filters label{font-size:.8rem;color:var(--t2);display:flex;align-items:center;gap:.4rem}
.filters select{background:var(--s);color:var(--t);border:1px solid var(--b);border-radius:4px;padding:.3rem .5rem;font-family:inherit;font-size:.8rem;cursor:pointer}
.filters select:focus{outline:none;border-color:var(--c)}
.filter-count{font-size:.75rem;color:var(--t2);margin-left:auto}
th[data-sort]{cursor:pointer;user-select:none}
th[data-sort]:hover{color:var(--c)}
.sort-arrow{font-size:.6rem;vertical-align:middle}
```

### CSS Chain Badges
```css
.chain-solana,.chain-sol{background:#9945ff22;color:#9945ff}
.chain-base{background:#0052ff22;color:#0052ff}
.chain-ethereum,.chain-eth{background:#627eea22;color:#627eea}
.chain-bsc,.chain-bnb{background:#f3ba2f22;color:#f3ba2f}
.chain-arbitrum{background:#28a0f022;color:#28a0f0}
.chain-polygon,.chain-pos{background:#8247e522;color:#8247e5}
.chain-avalanche{background:#e8414222;color:#e84142}
.chain-sui{background:#4da2ff22;color:#4da2ff}
.chain-optimism{background:#ff042022;color:#ff0420}
```

### JavaScript Helpers (copy to every page)
```javascript
function chain_cls(c){
  c=(c||"").toLowerCase();
  return["solana","sol","base","ethereum","eth","bsc","bnb","arbitrum","polygon","polygon-pos","avalanche","sui","optimism"].includes(c)?"chain-"+c:"";
}
function chain_label(c){
  return{solana:"Solana",sol:"Solana",base:"Base",ethereum:"Ethereum",eth:"Ethereum",
    bsc:"BNB Chain",bnb:"BNB Chain",arbitrum:"Arbitrum",polygon:"Polygon",
    "polygon-pos":"Polygon",avalanche:"Avalanche",sui:"Sui",optimism:"Optimism"}
  [(c||"").toLowerCase()]||c||"Unknown";
}
function block_url(addr,chain){
  chain=(chain||"").toLowerCase();
  if(chain==="solana"||chain==="sol")return"https://solscan.io/account/"+addr;
  if(chain==="base")return"https://basescan.org/address/"+addr;
  if(chain==="bsc"||chain==="bnb")return"https://bscscan.com/address/"+addr;
  if(chain==="arbitrum")return"https://arbiscan.io/address/"+addr;
  if(chain==="polygon"||chain==="polygon-pos")return"https://polygonscan.com/address/"+addr;
  if(chain==="avalanche")return"https://snowtrace.io/address/"+addr;
  if(chain==="optimism")return"https://optimistic.etherscan.io/address/"+addr;
  return"https://etherscan.io/address/"+addr;
}
```

### Chain Filter Population
```javascript
// After fetching data:
const chains=new Set(ALL_DATA.map(t=>chain_label(t.chain)).filter(Boolean));
const sel=document.getElementById("filter-chain");
[...chains].sort().forEach(c=>{
  const o=document.createElement("option");o.value=c;o.textContent=c;sel.appendChild(o);
});
sel.addEventListener("change",applyFilters);
```

### Filter + Sort Logic
```javascript
let ALL_DATA=[], sortKey="score", sortDir=-1;
function applyFilters(){
  const chain=document.getElementById("filter-chain").value;
  const mcap=document.getElementById("filter-mcap").value;
  let filtered=ALL_DATA.filter(t=>{
    if(chain && chain_label(t.chain)!==chain)return false;
    if(mcap && (t.mcap_tier||"")!==mcap)return false;
    return true;
  });
  filtered.sort((a,b)=>{
    let va=a[sortKey]||0, vb=b[sortKey]||0;
    if(typeof va==="string")return sortDir*va.localeCompare(vb);
    return sortDir*(va-vb);
  });
  renderTable(filtered);
  document.getElementById("filter-count").textContent=filtered.length+" of "+ALL_DATA.length;
}
```

### Column Sorting
```javascript
document.querySelectorAll("th[data-sort]").forEach(th=>{
  th.style.cursor="pointer";
  th.addEventListener("click",()=>{
    const key=th.dataset.sort;
    if(sortKey===key)sortDir*=-1; else{sortKey=key;sortDir=key==="symbol"?1:-1;}
    document.querySelectorAll("th[data-sort]").forEach(h=>h.querySelector(".sort-arrow").textContent="");
    th.querySelector(".sort-arrow").textContent=sortDir>0?" \u25B2":" \u25BC";
    applyFilters();
  });
});
```

### Nav Bar (consistent across all pages)
```html
<nav>
<div class="logo">HERMES <span>&#9670;</span> SCREENER</div>
<div class="nav">
  <a href="index.html">Tokens</a>
  <a href="wallets.html">Smart Money</a>
  <a href="cross-tokens.html">Tokens×Wallets</a>
  <a href="cross-wallets.html">Wallets×Tokens</a>
  <a href="tiered.html">Market Cap Tiers</a>
  <a href="smart-money.html">SM Tokens</a>
  <a href="smart-money-wallets.html">SM Wallets</a>
  <a href="smart-money-feed.html">SM Feed</a>
  <a href="columns.html">Guide</a>
  <a href="https://github.com/TerexitariusStomp/hermes-token-screener">GitHub</a>
</div></nav>
```

## Market Cap Tier Export Helper
```python
MCAP_TIERS = [
    (0, 50_000, "< $50K"),
    (50_000, 250_000, "$50K - $250K"),
    (250_000, 1_000_000, "$250K - $1M"),
    (1_000_000, 10_000_000, "$1M - $10M"),
    (10_000_000, 100_000_000, "$10M - $100M"),
    (100_000_000, float("inf"), "$100M+"),
]

def mcap_tier_label(fdv: float) -> str:
    for low, high, label in MCAP_TIERS:
        if low <= (fdv or 0) < high:
            return label
    return "< $50K"
```

## Chain Normalization (export)
```python
CHAIN_MAP = {
    "solana": "solana", "sol": "solana",
    "ethereum": "ethereum", "eth": "ethereum",
    "base": "base", "bsc": "BNB", "binance": "BNB",
    "arbitrum": "Arbitrum", "polygon": "Polygon",
    "avalanche": "Avalanche", "sui": "Sui",
}

def normalize_chain(chain, dex_url=""):
    # Try dex_url first (dexscreener.com/{chain}/{addr})
    if dex_url and "dexscreener.com" in dex_url:
        parts = dex_url.split("/")
        if len(parts) >= 4:
            url_chain = parts[3].lower()
            if url_chain in CHAIN_MAP:
                return CHAIN_MAP[url_chain]
    return CHAIN_MAP.get((chain or "").lower(), chain or "unknown")
```

## Dexscreener URL Fallback
Always generate Dexscreener URLs for tokens without dex_url:
```python
"dex_url": enriched.get("dex_url", "") or f"https://dexscreener.com/{chain.lower()}/{addr}",
```
Dexscreener URL format: `dexscreener.com/{chain}/{address}` where chain is lowercase slug (solana, base, ethereum, bsc).

## Date/Time Display (for feed pages)
Use actual datetime instead of relative "X ago":
```javascript
function fmt_date(ts){
  if(!ts)return"\u2014";
  const d=new Date(ts*1000);
  return d.toISOString().slice(0,16).replace("T"," ");
}
```

## DEX Sub-Object Flattening (export_tokens)
Enricher data has fields nested under `dex` sub-object. The frontend expects them at top level:
```python
for token in tokens:
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

## Best-File Selection for Export
When multiple enriched files exist (top100.json, top100_phase4_social.json), pick the one with the most tokens:
```python
best_count = 0
for src in candidate_files:
    with open(src) as f:
        raw = json.load(f)
    candidate = {t["contract_address"]: t for t in raw.get("tokens", []) if t.get("contract_address")}
    if len(candidate) > best_count:
        enriched_lookup = candidate
        best_count = len(candidate)
```

## Pitfalls
- Chain names inconsistent across sources (sol vs solana, eth vs ethereum, bsc vs BNB)
- Dexscreener URLs in dex_url field use chain slugs that may differ from display names
- Market cap must come from dex sub-object (`dex.fdv`) not top-level (`token.fdv`)
- Each page needs its own sort state (sortKey, sortDir) — can't share
- Nav bar must be updated on ALL pages when adding new links
- Enricher writes to top100.json and phase files differently — always check which has more data
- Wallet links must use chain-aware block_url() not hardcoded blockscan.com
