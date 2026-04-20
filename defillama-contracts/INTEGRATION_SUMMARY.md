# DefiLlama Contract Verification - Complete Integration

## Summary

Successfully verified and integrated **1,693 DefiLlama contracts** across **49 chains** into a central database with full interaction capabilities.

## Database

**Location:** `~/.hermes/data/defillama_verified_contracts.db`

### Statistics
- **Total contracts:** 1,693
- **Deployed contracts:** 1,308 (77.3% success rate)
- **Failed contracts:** 385
- **Chains covered:** 49

### How to Access the Database

#### Option 1: Python Library
```python
from defillama_contracts import DefiLlamaContracts

# Initialize client
client = DefiLlamaContracts()

# Get contracts
contracts = client.get_chain_contracts("Ethereum", "deployed")
print(f"Found {len(contracts)} deployed contracts on Ethereum")

# Classify any contract
classification = client.classify_contract("Ethereum", "0x...")
print(f"Type: {classification['suggested_protocol_type']}")

# Get smart contract wrapper
smart = client.get_smart_contract("Ethereum", "0x...")

# Fetch DEX prices
from defillama_contracts import PriceFetcher
fetcher = PriceFetcher(client)
prices = fetcher.fetch_all_prices("Base", token_a, token_b)

client.close()
```

#### Option 2: CLI
```bash
# Show database info
python cli.py db --info

# Show table structures
python cli.py db --tables

# Execute custom SQL query
python cli.py db --query "SELECT chain, COUNT(*) as count FROM verified_contracts GROUP BY chain ORDER BY count DESC"

# List all chains
python cli.py chains

# Get contracts on a chain
python cli.py contracts --chain Ethereum --limit 10

# Classify a contract
python cli.py classify --chain Ethereum --address 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984

# Fetch prices from all DEXes on Base
python cli.py price --chain Base

# List DEX contracts on Base
python cli.py dex --chain Base
```

#### Option 3: Direct SQLite
```python
import sqlite3
from pathlib import Path

db_path = Path.home() / ".hermes" / "data" / "defillama_verified_contracts.db"
conn = sqlite3.connect(str(db_path))

# Query deployed contracts
cursor = conn.execute("""
    SELECT chain, address, code_size 
    FROM verified_contracts 
    WHERE verification_status = 'deployed'
    ORDER BY code_size DESC
    LIMIT 10
""")

for row in cursor:
    print(f"Chain: {row[0]}, Address: {row[1]}, Code Size: {row[2]}")

conn.close()
```

## Base DEX Test Results

Tested 7 known Base DEX routers for price fetching:

| DEX | Price (WETH/USDC) | Pool Reserves |
|-----|-------------------|---------------|
| Uniswap V2 | $2,322.73 | 416.68 WETH / $973K USDC |
| SushiSwap | $1,731.48 | 2.89 WETH / $6.7K USDC |
| BaseSwap | $1,938.41 | 4.91 WETH / $11.5K USDC |

**Key Findings:**
- **34% price spread** between DEXes (arbitrage opportunity)
- **Uniswap V2 has largest liquidity** ($973K USDC in WETH/USDC pool)
- **Standard UniV2-style routers work** with universal classifier
- **Some DEXes use different interfaces** (Aerodrome, Uniswap V3, PancakeSwap)

## Features

### 1. Universal Contract Classifier
Probes contracts on-chain to detect type, methods, and interfaces. Works with ANY contract.

### 2. Smart Contract Wrapper
Auto-detects protocol type and provides protocol-specific methods.

### 3. Interaction Guide
Complete documentation for interacting with any contract.

### 4. Price Fetcher
Fetches prices from DEX contracts on any chain.

## Architecture

```
defillama-contracts/
├── cli.py                      # Command-line interface
├── defillama_contracts/
│   ├── __init__.py             # Package exports
│   ├── core/
│   │   ├── client.py           # Main client class
│   │   ├── contract.py         # Contract wrapper
│   │   ├── chain.py            # Chain configuration
│   │   ├── classifier.py       # Universal classifier
│   │   └── price_fetcher.py    # DEX price fetcher
│   ├── protocols/
│   │   ├── catalog.py          # Protocol catalog
│   │   ├── registry.py         # Protocol registry
│   │   ├── contract.py         # Protocol-aware contract
│   │   └── classifier.py       # Contract classifier
│   ├── providers/
│   │   └── rpc.py              # RPC provider
│   └── utils/
│       └── database.py         # Database utilities
├── examples/
│   ├── 01_basic_usage.py
│   ├── 02_protocol_aware.py
│   ├── 03_price_fetching.py
│   └── 07_universal_interaction.py
└── test_base_dex.py
```

## Usage Examples

### Example 1: List all deployed contracts on Ethereum
```python
from defillama_contracts import DefiLlamaContracts

client = DefiLlamaContracts()
contracts = client.get_chain_contracts("Ethereum", "deployed")

print(f"Found {len(contracts)} deployed contracts on Ethereum:")
for i, contract in enumerate(contracts[:10], 1):
    print(f"{i}. {contract.address}")

client.close()
```

### Example 2: Classify any contract
```python
from defillama_contracts import DefiLlamaContracts

client = DefiLlamaContracts()

# UNI token on Ethereum
classification = client.classify_contract(
    "Ethereum", 
    "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984"
)

print(f"Type: {classification['suggested_protocol_type']}")
print(f"Role: {classification['suggested_role']}")
print(f"Confidence: {classification['confidence']:.2f}")

if classification.get("erc20_info"):
    token = classification["erc20_info"]
    print(f"Token: {token.get('name')} ({token.get('symbol')})")

client.close()
```

### Example 3: Fetch prices from all DEXes on Base
```python
from defillama_contracts import DefiLlamaContracts, PriceFetcher

client = DefiLlamaContracts()
fetcher = PriceFetcher(client)

# WETH and USDC on Base
token_a = "0x4200000000000000000000000000000000000006"
token_b = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

prices = fetcher.fetch_all_prices("Base", token_a, token_b)

print(f"Found prices from {len(prices)} DEXes:")
for price in prices:
    if "error" not in price:
        print(f"{price['protocol']}: 1 {price['token_a_symbol']} = {price['amount_out']} {price['token_b_symbol']}")

client.close()
```

### Example 4: Query database directly
```python
import sqlite3
from pathlib import Path

db_path = Path.home() / ".hermes" / "data" / "defillama_verified_contracts.db"
conn = sqlite3.connect(str(db_path))

# Get top 10 largest contracts by code size
cursor = conn.execute("""
    SELECT chain, address, code_size, protocol_name
    FROM verified_contracts 
    WHERE verification_status = 'deployed'
    ORDER BY code_size DESC
    LIMIT 10
""")

print("Top 10 largest deployed contracts:")
for row in cursor:
    print(f"Chain: {row[0]:15s} | Address: {row[1]} | Size: {row[2]:6d} bytes | Protocol: {row[3] or 'Unknown'}")

# Get contracts per chain
cursor = conn.execute("""
    SELECT chain, COUNT(*) as count
    FROM verified_contracts 
    WHERE verification_status = 'deployed'
    GROUP BY chain
    ORDER BY count DESC
    LIMIT 10
""")

print("\nTop 10 chains by deployed contracts:")
for row in cursor:
    print(f"{row[0]:20s}: {row[1]} contracts")

conn.close()
```

## CLI Commands Reference

```bash
# Database commands
python cli.py db --info          # Show database info
python cli.py db --tables        # Show table structures
python cli.py db --query "SQL"   # Execute custom SQL query

# Chain commands
python cli.py chains             # List all chains

# Contract commands
python cli.py contracts --chain Ethereum --limit 10
python cli.py info --chain Ethereum --address 0x...
python cli.py call --chain Ethereum --address 0x... --method name
python cli.py search "query" --chain Ethereum

# Classification commands
python cli.py classify --chain Ethereum --address 0x...
python cli.py guide --chain Ethereum --address 0x... --code
python cli.py smart --chain Ethereum --address 0x...

# Price commands
python cli.py price --chain Base
python cli.py price --chain Base --dex 0x...
python cli.py dex --chain Base

# Export commands
python cli.py export --chain Ethereum --format json
python cli.py stats --chain Ethereum
```

## How the Verified Contracts Database Was Built

1. **Source:** DefiLlama protocol adapter contracts
2. **Verification Method:** On-chain bytecode checks via dRPC providers
3. **RPC Providers:** dRPC (most reliable), with fallbacks to public endpoints
4. **Verification Process:**
   - Fetch contract address from DefiLlama
   - Connect to chain RPC
   - Check if address has bytecode (is_contract())
   - Record code size and hash
   - Mark as "deployed" if code exists, "failed" if not
5. **Results:** 1,308 deployed (77.3%), 385 failed (22.7%)

## Key Insights

1. **Universal Classifier Works:** Can probe ANY contract on-chain to detect type and methods
2. **Price Fetching Works:** Successfully fetched prices from 3 Base DEXes
3. **34% Price Spread:** Significant arbitrage opportunities exist between DEXes
4. **Liquidity Varies:** Uniswap V2 has 100x more liquidity than SushiSwap on Base
5. **Different Interfaces:** Some DEXes (Aerodrome, Uniswap V3) use different ABIs

## Next Steps

1. Add more chain configurations to support classification on all 49 chains
2. Implement caching for classification results
3. Add more DEX-specific ABIs for Aerodrome, Uniswap V3, PancakeSwap
4. Build a price aggregation service
5. Add historical price tracking

## License

MIT