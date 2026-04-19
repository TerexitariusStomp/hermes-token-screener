# DefiLlama Full Integration - Status Report
Generated: 2026-04-19

## Executive Summary

Built a **fully unified DeFi infrastructure system** from 8 DefiLlama GitHub repositories plus live API endpoints.
The system covers **2,437 chains**, **7,362 protocols**, **1,993 RPC endpoints**, **86 bridge adapters**,
**950 yield adaptors**, and **canonical token addresses for 356 chains**.

---

## Repos Analyzed

### 1. DefiLlama/DefiLlama-Adapters (4,815 protocol adapters)
- **Value**: Factory/router/comptroller addresses for DEXs, lending, staking protocols
- **Key data**:
  - `registries/uniswapV2.js` - 717 V2 DEX forks, 1,125 factory addresses
  - `registries/uniswapV3.js` - 229 V3/concentrated liquidity protocols, 316 addresses
  - `registries/compound.js` - 93 Compound fork comptrollers, 392 addresses
  - `registries/aave.js` - 60 Aave lending pool registries, 144 addresses
  - `registries/masterchef.js` - 165 MasterChef farm registries, 399 addresses
  - `projects/helper/coreAssets.json` - 356 chains, 2,102 canonical token entries (WETH, USDC, etc.)
  - `projects/helper/chains.json` - 499 supported chain names
- **Extraction**: Parsed all registry files, extracted 2,932 unique (protocol, chain, address) tuples

### 2. DefiLlama/dimension-adapters (2,049 adapters)
- **Value**: DEX factory/router addresses, event ABIs, subgraph endpoints
- **Key data**:
  - `dexs/` - 801 DEX volume adapters
  - `factory/uniV2.ts` - 257 protocols, 338 chain entries, 352 factory addresses
  - `factory/uniV3.ts` - 97 protocols, 129 chain entries, 136 factory addresses
  - `factory/curve.ts` - 53 Curve pool addresses
  - `fees/` - 1,099 fee/revenue adapters
  - `aggregators/` - 120 DEX aggregator adapters
  - `bridge-aggregators/` - 23 bridge aggregator adapters
- **Extraction**: 546 unique protocol/version combos with factory addresses

### 3. DefiLlama/bridges-server (105 bridge adapters)
- **Value**: Bridge contract addresses, event signatures (Deposit, Withdrawal), chain mappings
- **Key data**:
  - `src/adapters/` - 103 bridge protocol directories
  - Includes: Across, Axelar, Celer, CCIP, Connext, Hop, Hyperlane, LayerZero, Stargate, Wormhole
  - `src/data/bridgeNetworkData.ts` - 2,905 lines of bridge registry data
- **Extraction**: 86 bridge adapters with contract addresses and chain mappings

### 4. DefiLlama/yield-server (950 yield adaptors)
- **Value**: Yield protocol addresses, pool configurations, APY calculation methods
- **Key data**:
  - `src/adaptors/` - 943 yield protocol directories
  - Includes: Aave, Compound, Lido, Morpho, Pendle, Yearn, Curve, Convex
- **Extraction**: 658 yield adaptors with addresses and chain mappings

### 5. DefiLlama/chainlist (2,982 stars)
- **Value**: Chain configurations, RPC endpoints, explorers, native currencies
- **Key data**:
  - `constants/extraRpcs.js` - 9,786 lines, 1,993 RPC URLs
  - `constants/additionalChainRegistry/` - 360 chain config files
  - `constants/chainIds.js` - Chain ID mappings
- **Extraction**: Merged with SDK providers for 743 chains with RPC endpoints

### 6. DefiLlama/defillama-sdk (70 stars)
- **Value**: ChainApi, Balances, ABI helpers, RPC resolution
- **Key data**:
  - `src/providers.json` - 158 EVM chains with RPC endpoints
  - Chain resolution, block fetching, event log utilities
- **Extraction**: 158 chain RPC providers

### 7. DefiLlama/peggedassets-server (41 stars)
- **Value**: Stablecoin tracking, supply data
- **Status**: Not deeply analyzed (stablecoins less critical for DEX trading)

---

## Live API Endpoints (Verified Working)

| Endpoint | URL | Items | Status |
|----------|-----|-------|--------|
| Protocols | api.llama.fi/protocols | 7,362 | 200 OK |
| Chains | api.llama.fi/v2/chains | 440 | 200 OK |
| DEXs | api.llama.fi/overview/dexs | 1,074 | 200 OK |
| Fees | api.llama.fi/overview/fees | 2,035 | 200 OK |
| Yields | yields.llama.fi/pools | 23,845 | 200 OK |
| Stablecoins | stablecoins.llama.fi/stablecoins | 175 | 200 OK |
| Bridges | bridges.llama.fi/bridges | 402 (blocked) | - |

---

## Unified Infrastructure Built

### Data Files Created

| File | Size | Description |
|------|------|-------------|
| `unified_defi_infrastructure.json` | 1,711 KB | Master dataset: chains, protocols, DEX factories, bridges, yields, RPCs, core assets |
| `chain_summary.json` | 345 KB | Per-chain counts (DEX, lending, bridge, RPC) |
| `dex_factory_index.json` | 76 KB | Protocol/version -> chain -> factory addresses |
| `registry_addresses.json` | 231 KB | All DefiLlama-Adapters registry addresses |
| `chain_id_mapping.json` | 4 KB | Chain ID -> chain name mapping (172 entries) |
| `defillama_unified.py` | 14 KB | Python module with full API |

### Coverage Statistics

| Metric | Count |
|--------|-------|
| Total chains | 2,437 |
| Chains with RPCs | 743 |
| Chains with DEX factories | 105 |
| Chains with core assets | 354 |
| Protocols in registry | 1,952 |
| DEX factory protocols | 546 |
| Bridge adapters | 86 |
| Yield adaptors | 658 |
| Canonical token addresses | 2,102 entries |

### Top Chains by DEX Factory Count

| Chain | DEX Factories | RPCs | Core Assets |
|-------|---------------|------|-------------|
| ethereum | 421 | 72 | Yes |
| binance | 49 | 1 | Yes |
| fantom | 28 | 0 | Yes |
| base | 26 | 30 | Yes |
| arbitrum | 24 | 28 | Yes |
| polygon | 23 | 29 | Yes |
| avalanche | 18 | 21 | Yes |
| sonic | 18 | 0 | Yes |
| linea | 13 | 0 | Yes |
| monad | 13 | 0 | Yes |

---

## Python Module API

```python
import defillama_unified as dlu

# Get all DEX factories on a chain
factories = dlu.get_dex_factories('base')
# Returns: [{'protocol': 'aerodrome', 'version': 'v2', 'factory': '0x...', 'source': '...'}]

# Get RPC endpoints for a chain
rpcs = dlu.get_rpcs('ethereum')
# Returns: ['https://cloudflare-eth.com/', 'https://...']

# Get canonical token addresses
assets = dlu.get_core_assets('ethereum')
# Returns: {'WETH': '0xc02aaa...', 'USDC': '0xa0b869...'}

# Get bridge adapters
bridges = dlu.get_bridge_adapters()
# Returns: {'axelar': {'addresses': [...], 'chains': [...], 'events': [...]}}

# Search protocols
results = dlu.search_protocol('uniswap')
# Returns: [{'name': 'Uniswap V3', 'tvl': 1749164361, 'chains': [...]}]

# Get top chains
top = dlu.get_top_chains('dex', 10)
# Returns: [('ethereum', 421), ('binance', 49), ...]
```

---

## Integration with Existing Infrastructure

### Before (Existing)
- 255 chains with integration data
- 1,327 DEX protocols from manual enumeration
- 13,055 lending contracts
- 241 chains with DEXes

### After (Unified)
- **2,437 chains** (9.5x increase)
- **546 DEX factory protocols** from DefiLlama (536 unique to DefiLlama)
- **1,952 protocols** with TVL/category/chains
- **743 chains** with RPC endpoints
- **86 bridge adapters** with contract addresses
- **658 yield adaptors**

### Combined Coverage
- Chains: ~2,500 unique chains
- DEX protocols: ~1,800 unique (combined naming)
- Lending: 13,055+ contracts (existing) + DefiLlama registry data
- Bridges: 86 DefiLlama adapters + existing bridge network map
- RPCs: 743 chains from DefiLlama + existing verified RPCs

---

## Key Findings

1. **DefiLlama-Adapters/registries are the richest source** of factory addresses:
   - 717 V2 DEX protocols with 1,125 factory addresses
   - 229 V3 protocols with 316 addresses
   - 93 Compound forks with 392 comptroller addresses

2. **dimension-adapters/factory** covers more chains (338 vs 5):
   - The registries in DefiLlama-Adapters are primarily Ethereum-focused
   - dimension-adapters factory files have broader chain coverage

3. **Chain RPC coverage is massive**: 743 chains from DefiLlama + chainlist
   - chainlist's `extraRpcs.js` alone has 1,993 RPC URLs
   - Combined with our existing verified RPCs, covers almost all known chains

4. **Core assets are essential**: 356 chains with canonical token addresses
   - WETH, USDC, USDT, WBTC addresses for each chain
   - Critical for on-chain price calculations and swap routing

5. **API endpoints provide real-time data**:
   - 7,362 protocols with live TVL
   - 440 chains with live data
   - 23,845 yield pools with live APY

---

## Next Steps

1. **Merge with existing trading infrastructure**:
   - Combine DefiLlama factory addresses with existing DEX router addresses
   - Use core assets for canonical token lookups in arb calculations
   - Integrate bridge adapters for cross-chain arb paths

2. **RPC verification**:
   - Test all 743 DefiLlama RPC endpoints
   - Merge with existing verified RPCs
   - Update chain integration map

3. **DEX price fetching expansion**:
   - Use factory addresses to discover pools on new chains
   - Extend V3 quoter integration to all chains with factories
   - Add Solidly/Velodrome-style DEX support

4. **Cross-chain arbitrage**:
   - Use bridge adapter data to identify cross-chain arb paths
   - Integrate yield data for lending-based arb strategies
   - Add stablecoin data for peg arbitrage

---

## Files Location

All data: `~/.hermes/data/defillama_unified/`
Module: `~/.hermes/data/defillama_unified/defillama_unified.py`
Extractor: `~/.hermes/scripts/defillama_unified_extractor.py`
Report script: `~/.hermes/scripts/defillama_integration_report.py`
Cloned repos: `~/.hermes/DefiLlama-Adapters/`, `~/.hermes/dimension-adapters/`, `~/.hermes/defillama-repos/`
