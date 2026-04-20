# DefiLlama Verified Contracts Library

A comprehensive Python library for interacting with **1,693 verified DefiLlama contracts** across **49 chains**.

## Database

**Location:** `~/.hermes/data/defillama_verified_contracts.db`

- **Total contracts:** 1,693
- **Deployed contracts:** 1,308 (77.3% success rate)
- **Failed contracts:** 385
- **Chains covered:** 49

### Database Schema

```sql
-- Main contracts table
CREATE TABLE verified_contracts (
    id INTEGER PRIMARY KEY,
    chain TEXT NOT NULL,
    address TEXT NOT NULL,
    contract_type TEXT,
    protocol_name TEXT,
    verification_status TEXT CHECK(verification_status IN ('deployed', 'failed')),
    verification_source TEXT,
    rpc_used TEXT,
    code_hash TEXT,
    code_size INTEGER,
    is_proxy BOOLEAN,
    implementation_address TEXT,
    first_verified_at TIMESTAMP,
    last_verified_at TIMESTAMP,
    verification_attempts INTEGER,
    notes TEXT
);

-- Chain configurations
CREATE TABLE chain_configs (
    chain TEXT PRIMARY KEY,
    chain_id INTEGER,
    rpc_urls TEXT,
    native_token TEXT,
    block_time INTEGER,
    explorer_url TEXT,
    multicall_address TEXT
);

-- RPC status tracking
CREATE TABLE chain_rpc_status (
    id INTEGER PRIMARY KEY,
    chain TEXT,
    rpc_url TEXT,
    is_working BOOLEAN,
    last_checked TIMESTAMP,
    response_time_ms INTEGER,
    error_message TEXT
);
```

### Accessing the Database

```python
import sqlite3
from pathlib import Path

# Connect to database
db_path = Path.home() / ".hermes" / "data" / "defillama_verified_contracts.db"
conn = sqlite3.connect(str(db_path))

# Get all deployed contracts on Ethereum
cursor = conn.execute("""
    SELECT address, code_size 
    FROM verified_contracts 
    WHERE chain = 'Ethereum' AND verification_status = 'deployed'
    ORDER BY code_size DESC
    LIMIT 10
""")

for row in cursor:
    print(f"Address: {row[0]}, Code Size: {row[1]} bytes")

conn.close()
```

## Installation

```bash
pip install web3  # Required for on-chain interactions
```

## Quick Start

```python
from defillama_contracts import DefiLlamaContracts, PriceFetcher

# Initialize client
client = DefiLlamaContracts()

# Get all chains
chains = client.get_all_chains()
print(f"Available chains: {len(chains)}")

# Get deployed contracts on Ethereum
contracts = client.get_chain_contracts("Ethereum", "deployed", limit=10)
print(f"Ethereum contracts: {len(contracts)}")

# Classify any contract
classification = client.classify_contract("Ethereum", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984")
print(f"Type: {classification['suggested_protocol_type']}")
print(f"Role: {classification['suggested_role']}")

# Get smart contract wrapper
smart = client.get_smart_contract("Ethereum", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984")
info = smart.get_contract_info()
print(f"Token: {info.get('token', {}).get('name')}")

# Fetch DEX prices
fetcher = PriceFetcher(client)
token_a = "0x4200000000000000000000000000000000000006"  # WETH on Base
token_b = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # USDC on Base
prices = fetcher.fetch_all_prices("Base", token_a, token_b)

for price in prices:
    if "error" not in price:
        print(f"{price['protocol']}: 1 {price['token_a_symbol']} = {price['amount_out']} {price['token_b_symbol']}")

client.close()
```

## CLI Usage

```bash
# List all chains
python cli.py chains

# Get contracts on Ethereum
python cli.py contracts --chain Ethereum --limit 10

# Classify a contract
python cli.py classify --chain Ethereum --address 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984

# Get interaction guide
python cli.py guide --chain Ethereum --address 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984 --code

# Get smart contract wrapper
python cli.py smart --chain Ethereum --address 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984

# Fetch prices from all DEXes on Base
python cli.py price --chain Base

# Fetch price from specific DEX
python cli.py price --chain Base --dex 0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24

# List DEX contracts on a chain
python cli.py dex --chain Base

# Show database info
python cli.py db --info

# Show database tables
python cli.py db --tables

# Execute custom SQL query
python cli.py db --query "SELECT chain, COUNT(*) as count FROM verified_contracts GROUP BY chain ORDER BY count DESC"
```

## Features

### 1. Universal Contract Classifier

Probes contracts on-chain to detect type, methods, and interfaces. Works with ANY contract, not just registered protocols.

```python
# Classify any contract
classification = client.classify_contract("Ethereum", "0x...")

# Returns:
# - detected_categories: List of detected contract categories
# - suggested_template: Best matching template
# - suggested_role: Contract role (router, factory, pair, etc.)
# - suggested_protocol_type: Protocol type (DEX, lending, bridge, etc.)
# - confidence: Confidence score (0.0 to 1.0)
# - erc20_info: ERC20 token info if available
# - interaction_methods: List of methods to interact with
```

### 2. Smart Contract Wrapper

Auto-detects protocol type and provides protocol-specific methods.

```python
# Get smart contract wrapper
smart = client.get_smart_contract("Ethereum", "0x...")

# Access protocol-specific methods
info = smart.get_contract_info()
print(f"Protocol: {smart.protocol_name}")
print(f"Role: {smart.role}")
print(f"Methods: {len(info.get('methods', []))}")
```

### 3. Interaction Guide

Complete documentation for interacting with any contract.

```python
# Get interaction guide
guide = client.get_contract_interaction_guide("Ethereum", "0x...")

# Returns:
# - contract: Basic info (address, chain, type, role, confidence)
# - token_info: ERC20 token info if available
# - read_methods: List of read-only methods
# - write_methods: List of write methods with gas estimates
# - example_code: Python code example for interaction
```

### 4. Price Fetcher

Fetches prices from DEX contracts on any chain.

```python
from defillama_contracts import PriceFetcher

fetcher = PriceFetcher(client)

# Fetch from specific DEX
result = fetcher.fetch_price(
    chain="Base",
    dex_address="0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",
    token_a="0x4200000000000000000000000000000000000006",
    token_b="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    amount=1.0
)

# Fetch from all DEXes on chain
results = fetcher.fetch_all_prices("Base", token_a, token_b)
```

## Base DEX Test Results

Tested 7 known Base DEX routers:

| DEX | Price (WETH/USDC) | Pool Size |
|-----|-------------------|-----------|
| Uniswap V2 | $2,322.73 | 416.68 WETH / $973K USDC |
| SushiSwap | $1,731.48 | 2.89 WETH / $6.7K USDC |
| BaseSwap | $1,938.41 | 4.91 WETH / $11.5K USDC |

**Price spread:** 34% between lowest and highest

## Supported Chains

- Ethereum
- Base
- Arbitrum
- Optimism
- Polygon
- Avalanche
- BSC
- Fantom
- Gnosis
- And 40+ more...

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

## License

MIT