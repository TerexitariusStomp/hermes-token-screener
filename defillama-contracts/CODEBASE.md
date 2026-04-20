# DefiLlama Contracts Codebase Structure

## Overview

This codebase provides a comprehensive Python library for interacting with 1,693 verified DefiLlama contracts across 49 chains. The library is designed to make it easy for AI systems and developers to interact with DeFi smart contracts.

## Directory Structure

```
~/.hermes/defillama-contracts/
├── __init__.py                    # Package initialization
├── cli.py                         # Command-line interface
├── quickstart.py                  # Quick start demonstration
├── setup.py                       # Package setup
├── requirements.txt               # Dependencies
├── README.md                      # Documentation
│
├── core/                          # Core functionality
│   ├── __init__.py
│   ├── client.py                  # Main client class
│   ├── contract.py                # Contract abstraction
│   └── chain.py                   # Chain abstraction
│
├── providers/                     # RPC providers
│   ├── __init__.py
│   └── rpc.py                     # RPC provider with fallback
│
├── utils/                         # Utilities
│   ├── __init__.py
│   ├── abi.py                     # ABI resolver
│   └── database.py                # Database utility
│
├── examples/                      # Example scripts
│   ├── __init__.py
│   ├── 01_get_ethereum_contracts.py
│   ├── 02_interact_with_contract.py
│   ├── 03_batch_calls.py
│   ├── 04_multi_chain.py
│   └── 05_dex_interactions.py
│
└── tests/                         # Test scripts
    ├── __init__.py
    └── test_library.py
```

## Core Components

### 1. DefiLlamaContracts (`core/client.py`)

The main client class that provides the primary interface for interacting with contracts.

**Key Features:**
- Get contracts by chain
- Get specific contract instances
- Search contracts
- Batch call operations
- Export contracts in multiple formats
- Database statistics

**Usage:**
```python
from defillama_contracts import DefiLlamaContracts

client = DefiLlamaContracts()
contracts = client.get_chain_contracts("Ethereum", "deployed")
contract = client.get_contract("Ethereum", "0x...")
client.close()
```

### 2. Contract (`core/contract.py`)

Represents a smart contract on a specific chain.

**Key Features:**
- Call contract methods (read and write)
- Get contract events
- Get contract balance
- Get contract bytecode
- Detect proxy contracts

**Usage:**
```python
contract = client.get_contract("Ethereum", "0x...")
name = contract.call("name", [])
balance = contract.get_balance()
events = contract.get_events("Transfer")
```

### 3. Chain (`core/chain.py`)

Represents a blockchain network.

**Key Features:**
- Predefined configurations for 49+ chains
- Chain ID, RPC URLs, native token
- Explorer URLs
- Multicall addresses

**Usage:**
```python
from defillama_contracts.core.chain import Chain

ethereum = Chain.get_chain("Ethereum")
print(f"Chain ID: {ethereum.chain_id}")
print(f"RPC URLs: {ethereum.rpc_urls}")
```

### 4. RPCProvider (`providers/rpc.py`)

Handles blockchain RPC calls with multi-provider fallback.

**Key Features:**
- Multiple RPC provider support
- Automatic fallback on failure
- Rate limiting
- Common JSON-RPC methods

**Usage:**
```python
from defillama_contracts.providers.rpc import RPCProvider

provider = RPCProvider()
balance = provider.get_balance("Ethereum", "0x...")
code = provider.get_code("Ethereum", "0x...")
```

### 5. ABIResolver (`utils/abi.py`)

Resolves and manages contract ABIs.

**Key Features:**
- ABI fetching from multiple sources
- Method signature encoding/decoding
- Event signature creation
- Common method signatures

**Usage:**
```python
from defillama_contracts.utils.abi import ABIResolver

resolver = ABIResolver()
encoded = resolver.encode_method_call("balanceOf(address)", ["0x..."])
```

### 6. ContractDatabase (`utils/database.py`)

Database utility for accessing contract data.

**Key Features:**
- SQLite database access
- Contract queries by chain/status
- Chain configuration
- Export functionality

**Usage:**
```python
from defillama_contracts.utils.database import ContractDatabase

db = ContractDatabase()
contracts = db.get_contracts_by_chain("Ethereum", "deployed")
```

## Examples

### 1. Get Ethereum Contracts
```python
# examples/01_get_ethereum_contracts.py
from defillama_contracts import DefiLlamaContracts

client = DefiLlamaContracts()
eth_contracts = client.get_chain_contracts("Ethereum", "deployed")
print(f"Found {len(eth_contracts)} contracts")
client.close()
```

### 2. Interact with UNI Token
```python
# examples/02_interact_with_contract.py
from defillama_contracts import DefiLlamaContracts

client = DefiLlamaContracts()
contract = client.get_contract("Ethereum", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984")

name = contract.call("name", [])
symbol = contract.call("symbol", [])
print(f"Token: {name} ({symbol})")

client.close()
```

### 3. Batch Calls
```python
# examples/03_batch_calls.py
from defillama_contracts import DefiLlamaContracts

client = DefiLlamaContracts()
results = client.batch_call([
    {"chain": "Ethereum", "address": "0x...", "method": "name", "params": []},
    {"chain": "Ethereum", "address": "0x...", "method": "symbol", "params": []}
])
client.close()
```

### 4. Multi-Chain Operations
```python
# examples/04_multi_chain.py
from defillama_contracts import DefiLlamaContracts

client = DefiLlamaContracts()
chains = client.get_all_chains()
print(f"Total chains: {len(chains)}")

for chain in chains:
    stats = client.get_chain_stats(chain)
    print(f"{chain}: {stats.get('deployed', 0)} deployed")
client.close()
```

### 5. DEX Interactions
```python
# examples/05_dex_interactions.py
from defillama_contracts import DefiLlamaContracts

client = DefiLlamaContracts()

# Uniswap V2 Router
router = client.get_contract("Ethereum", "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")
factory = router.call("factory", [])
weth = router.call("WETH", [])

print(f"Factory: {factory}")
print(f"WETH: {weth}")

client.close()
```

## CLI Tool

The library includes a command-line interface for easy interaction.

### Usage

```bash
# List all chains
python -m defillama_contracts.cli chains

# Get contracts on Ethereum
python -m defillama_contracts.cli contracts --chain Ethereum

# Get specific contract info
python -m defillama_contracts.cli info --chain Ethereum --address 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984

# Call contract method
python -m defillama_contracts.cli call --chain Ethereum --address 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984 --method name

# Export contracts
python -m defillama_contracts.cli export --chain Ethereum --format json

# Show statistics
python -m defillama_contracts.cli stats

# Search contracts
python -m defillama_contracts.cli search "uniswap"
```

## Quick Start

Run the quick start script to see the library in action:

```bash
cd ~/.hermes/defillama-contracts
python quickstart.py
```

## Testing

Run the test suite:

```bash
cd ~/.hermes/defillama-contracts
python -m pytest tests/
```

## Installation

### From Source

```bash
cd ~/.hermes/defillama-contracts
pip install -e .
```

### With Optional Dependencies

```bash
# With Web3 support
pip install -e ".[web3]"

# With all optional dependencies
pip install -e ".[full]"

# With development dependencies
pip install -e ".[dev]"
```

## Database

The library uses a SQLite database with the following structure:

### Tables

1. **verified_contracts**: Main contracts table
   - chain: Chain name
   - address: Contract address
   - verification_status: "deployed" or "failed"
   - provider: RPC provider used
   - code_size: Contract bytecode size
   - code_hash: Contract bytecode hash
   - verification_time: Verification timestamp

2. **chain_configs**: Chain configurations
   - chain: Chain name
   - chain_id: Chain ID
   - rpc_urls: JSON array of RPC URLs
   - native_token: Native token symbol
   - block_time: Block time in seconds
   - explorer_url: Block explorer URL
   - multicall_address: Multicall contract address

3. **improvement_pass_results**: Verification improvement results
   - run_id: Improvement run ID
   - start_time: Start timestamp
   - end_time: End timestamp
   - duration_seconds: Run duration
   - statistics: JSON statistics
   - chain_breakdown: JSON chain breakdown
   - provider_breakdown: JSON provider breakdown

### Statistics

- **Total Contracts**: 1,693
- **Deployed Contracts**: 1,308 (77.3%)
- **Failed Contracts**: 385 (22.7%)
- **Chains**: 49

## Supported Chains

### EVM Chains (47)
- Ethereum (1)
- Binance Smart Chain (56)
- Arbitrum (42161)
- Base (8453)
- Polygon (137)
- Avalanche (43114)
- Optimism (10)
- Fantom (250)
- And 39 more...

### Non-EVM Chains (2)
- Solana
- Near

## API Reference

### DefiLlamaContracts

#### Methods

- `__init__(db_path=None)`: Initialize client
- `get_chain_contracts(chain, status="deployed", limit=None)`: Get contracts by chain
- `get_contract(chain, address)`: Get specific contract
- `get_chain(chain)`: Get chain instance
- `get_all_chains()`: Get all chains
- `get_chain_stats(chain)`: Get chain statistics
- `search_contracts(query, chain=None, status="deployed", limit=50)`: Search contracts
- `batch_call(calls, chain=None)`: Execute batch calls
- `export_contracts(chain=None, status="deployed", format="json")`: Export contracts
- `refresh_database()`: Refresh database
- `get_summary()`: Get database summary
- `close()`: Close connections

### Contract

#### Methods

- `call(method, params=[], abi=None, private_key=None, ...)`: Call contract method
- `get_events(event_name, from_block="latest", to_block="latest", topics=[])`: Get events
- `get_balance(token_address=None)`: Get balance
- `get_code()`: Get bytecode
- `is_contract()`: Check if address is contract
- `get_implementation()`: Get proxy implementation

### Chain

#### Methods

- `get_chain(name)`: Get predefined chain
- `get_all_chains()`: Get all predefined chains
- `get_evm_chains()`: Get all EVM chains
- `is_evm()`: Check if EVM compatible
- `is_solana()`: Check if Solana
- `get_explorer_url(address=None)`: Get explorer URL
- `get_rpc_url(index=0)`: Get RPC URL

### RPCProvider

#### Methods

- `get_balance(chain, address, block="latest")`: Get balance
- `get_code(chain, address, block="latest")`: Get bytecode
- `get_storage_at(chain, address, position, block="latest")`: Get storage
- `call_contract(chain, to, data, block="latest", ...)`: Call contract
- `estimate_gas(chain, to, data, ...)`: Estimate gas
- `get_gas_price(chain)`: Get gas price
- `send_transaction(chain, to, data, private_key, ...)`: Send transaction
- `get_logs(chain, address, topics, from_block="latest", to_block="latest")`: Get logs
- `get_block_number(chain)`: Get block number
- `get_transaction_count(chain, address, block="latest")`: Get nonce

## Error Handling

The library provides comprehensive error handling:

```python
try:
    contract = client.get_contract("Ethereum", "0x...")
    if contract:
        result = contract.call("methodName", [])
    else:
        print("Contract not found")
except Exception as e:
    print(f"Error: {e}")
```

## Performance Considerations

1. **Caching**: Contracts and chains are cached to reduce database queries
2. **Batch Operations**: Use `batch_call()` for multiple contract calls
3. **RPC Fallback**: Automatic fallback across multiple RPC providers
4. **Connection Pooling**: Database connections are managed efficiently

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License

## Support

For issues and questions:
- GitHub Issues: https://github.com/TerexitariusStomp/defillama-contracts/issues
- Email: hermeticsintellegencia@proton.me

## Changelog

### v1.0.0 (2026-04-20)
- Initial release
- Support for 1,693 verified contracts across 49 chains
- Multi-chain contract interactions
- Batch operations
- Export capabilities
- Comprehensive documentation
- CLI tool
- Test suite