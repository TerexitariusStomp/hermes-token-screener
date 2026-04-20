# Protocol Catalog Documentation

## Overview

The Protocol Catalog provides smart contract interaction patterns for different types of DeFi protocols. Instead of using generic contract calls, the catalog knows the specific methods and interfaces for each protocol type, making it easy to interact with DEXes, bridges, lending protocols, and more.

## Architecture

### Components

1. **ProtocolCatalog** (`catalog.py`)
   - Defines standard ABI patterns for each protocol type
   - Contains method signatures, gas estimates, and documentation
   - Provides templates for common protocol patterns

2. **ProtocolRegistry** (`registry.py`)
   - Maps specific protocols to their contract addresses
   - Links protocols to their templates
   - Provides protocol discovery by address

3. **ProtocolContract** (`contract.py`)
   - Wraps standard Contract with protocol awareness
   - Auto-detects protocol from address
   - Provides protocol-specific methods

### Protocol Types

| Type | Description | Examples |
|------|-------------|----------|
| DEX | Decentralized exchanges | Uniswap, Curve, PancakeSwap |
| BRIDGE | Cross-chain bridges | Stargate, LayerZero |
| LENDING | Lending/borrowing protocols | Aave, Compound, Morpho |
| YIELD | Yield farming/staking | Lido, Yearn |
| DERIVATIVES | Derivatives trading | dYdX, GMX |
| STABLECOIN | Stablecoin protocols | MakerDAO, Frax |
| GOVERNANCE | Governance contracts | Compound Governor, Aave Governance |
| AGGREGATOR | DEX aggregators | 1inch, Paraswap |
| ORACLE | Price oracles | Chainlink, Pyth |
| OTHER | Other protocols | ERC20, ERC721 |

### Contract Roles

| Role | Description | Common Methods |
|------|-------------|----------------|
| ROUTER | Swap routing | swapExactTokensForTokens, getAmountsOut |
| FACTORY | Pair/pool creation | createPair, getPair |
| PAIR | Liquidity pool | getReserves, swap |
| TOKEN | ERC20 token | transfer, approve, balanceOf |
| VAULT | Yield vault | deposit, withdraw |
| LENDING_POOL | Lending pool | supply, borrow, withdraw |
| BRIDGE_IN | Bridge entry point | bridge, claim |
| PRICE_FEED | Oracle price feed | latestAnswer, latestRoundData |
| STAKING | Staking contract | stake, withdraw, claimRewards |

## Usage

### Basic Usage

```python
from defillama_contracts import DefiLlamaContracts, ProtocolContract

# Initialize client
client = DefiLlamaContracts()

# Get a contract
contract = client.get_contract("Ethereum", "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")

# Wrap with protocol awareness
router = ProtocolContract(contract, "uniswap_v2", "router")

# Use protocol-specific methods
quote = router.get_swap_quote(amount_in, path)
router.swap_exact_tokens_for_tokens(amount_in, amount_out_min, path, to, private_key=key)

client.close()
```

### Auto-Detection

```python
from defillama_contracts import DefiLlamaContracts, ProtocolContract

client = DefiLlamaContracts()
contract = client.get_contract("Ethereum", "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")

# Auto-detect protocol
router = ProtocolContract(contract)

print(router.protocol_name)  # "uniswap_v2"
print(router.role)           # "router"
print(router.protocol_type)  # ProtocolType.DEX

client.close()
```

### Listing Protocols

```python
from defillama_contracts import registry
from defillama_contracts.protocols import ProtocolType

# List all protocols
protocols = registry.list_protocols()

# Get DEX protocols
dexes = registry.get_protocols_by_type(ProtocolType.DEX)

# Get protocols on Ethereum
eth_protocols = registry.get_protocols_by_chain("Ethereum")

# Find protocol by address
result = registry.find_protocol_by_address(
    "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
    "Ethereum"
)
if result:
    name, protocol, role = result
    print(f"{name} ({role})")
```

### Browsing Templates

```python
from defillama_contracts import catalog
from defillama_contracts.protocols import ProtocolType

# List all templates
templates = catalog.list_templates()

# Get DEX templates
dex_templates = catalog.get_templates_by_type(ProtocolType.DEX)

# Get router templates
router_templates = catalog.get_templates_by_role(ContractRole.ROUTER)

# Get specific template
uniswap_router = catalog.get_template("uniswap_v2_router")

# Get methods
methods = uniswap_router.methods
for method in methods:
    print(f"{method.name}: {method.signature}")
```

## Protocol-Specific Methods

### DEX (Uniswap V2 Style)

```python
router = ProtocolContract(contract, "uniswap_v2", "router")

# Read methods
factory = router.call_protocol_method("factory")
weth = router.call_protocol_method("WETH")

# Get swap quote
quote = router.get_swap_quote(amount_in, path)
print(f"Output: {quote['amount_out']}")

# Execute swap
tx_hash = router.swap_exact_tokens_for_tokens(
    amount_in=10**18,
    amount_out_min=10**6,
    path=[weth, usdc],
    to=my_address,
    private_key=my_key
)
```

### DEX (Curve Style)

```python
pool = ProtocolContract(contract, "curve", "router")

# Get pool info
a = pool.call_protocol_method("A")
fee = pool.call_protocol_method("fee")
balance0 = pool.call_protocol_method("balances", [0])

# Get swap quote
expected = pool.call_protocol_method("get_dy", [0, 1, amount_in])

# Execute swap
tx_hash = pool.call_protocol_method(
    "exchange",
    [0, 1, amount_in, min_dy],
    private_key=my_key
)
```

### Lending (Aave V3 Style)

```python
pool = ProtocolContract(contract, "aave_v3", "lending_pool")

# Supply
tx_hash = pool.supply(asset, amount, on_behalf_of, private_key=my_key)

# Withdraw
tx_hash = pool.withdraw(asset, amount, to, private_key=my_key)

# Borrow
tx_hash = pool.borrow(asset, amount, interest_rate_mode=2, private_key=my_key)

# Get account data
account_data = pool.get_user_account_data(user_address)
print(f"Health Factor: {account_data['healthFactor']}")
```

### Bridge

```python
bridge = ProtocolContract(contract, "stargate", "bridge")

# Estimate fees
fees = bridge.estimate_bridge_fees(token, amount, dest_chain_id)
print(f"Bridge fee: {fees['nativeFee']}")

# Bridge tokens
tx_hash = bridge.bridge_tokens(
    token=token_address,
    amount=amount,
    dest_chain_id=10,  # Optimism
    recipient=recipient_address,
    private_key=my_key
)
```

### Oracle

```python
oracle = ProtocolContract(contract, "chainlink", "price_feed")

# Get price
price_data = oracle.get_price()
answer = price_data['answer']
decimals = price_data['decimals']
price = answer / (10 ** decimals)
print(f"Price: ${price:.2f}")
```

### Staking

```python
staking = ProtocolContract(contract, "lido", "staking")

# Stake
tx_hash = staking.stake(amount, private_key=my_key)

# Check rewards
rewards = staking.get_staking_rewards(account)
print(f"Rewards: {rewards}")
```

## CLI Usage

### List Protocols

```bash
# List all protocols
python -m defillama_contracts.cli_protocols list

# Filter by type
python -m defillama_contracts.cli_protocols list --type dex

# Filter by chain
python -m defillama_contracts.cli_protocols list --chain Ethereum
```

### Show Protocol Details

```bash
# Basic info
python -m defillama_contracts.cli_protocols info uniswap_v2

# With methods
python -m defillama_contracts.cli_protocols info uniswap_v2 --methods
```

### List Templates

```bash
# List all templates
python -m defillama_contracts.cli_protocols templates

# Filter by type
python -m defillama_contracts.cli_protocols templates --type dex
```

### Show Methods

```bash
# Show methods for a template
python -m defillama_contracts.cli_protocols methods uniswap_v2_router
python -m defillama_contracts.cli_protocols methods aave_v3_pool
python -m defillama_contracts.cli_protocols methods oracle_chainlink
```

### Find Protocol by Address

```bash
# Find protocol for a contract
python -m defillama_contracts.cli_protocols search 0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D --chain Ethereum
```

### Verify Contract

```bash
# Verify contract matches expected protocol
python -m defillama_contracts.cli_protocols verify 0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D --chain Ethereum
```

## Registered Protocols

### DEX Protocols

| Protocol | Version | Chains | Templates |
|----------|---------|--------|-----------|
| Uniswap V2 | 2.0 | Ethereum, Arbitrum, Polygon, Optimism, Binance, Avalanche | router, factory, pair |
| Uniswap V3 | 3.0 | Ethereum, Arbitrum, Polygon, Optimism, Base, Avalanche, Binance | router, factory |
| Curve | 1.0 | Ethereum, Arbitrum, Polygon, Optimism, Avalanche, Fantom, Base | router |
| PancakeSwap | 2.0 | Binance, Ethereum, Arbitrum, Polygon, Base | router, factory, pair |
| SushiSwap | 2.0 | Ethereum, Arbitrum, Polygon, Optimism, Avalanche, Binance, Base, Fantom | router, factory, pair |
| Aerodrome | 1.0 | Base | router, factory, pair |
| Velodrome | 1.0 | Optimism | router, factory, pair |

### Lending Protocols

| Protocol | Version | Chains | Templates |
|----------|---------|--------|-----------|
| Aave V3 | 3.0 | Ethereum, Arbitrum, Polygon, Optimism, Avalanche, Fantom, Base, Gnosis, Binance | lending_pool |
| Compound V3 | 3.0 | Ethereum, Arbitrum, Polygon, Optimism, Base | lending_pool |
| Morpho | 1.0 | Ethereum, Base | lending_pool |

### Bridge Protocols

| Protocol | Version | Chains | Templates |
|----------|---------|--------|-----------|
| Stargate | 1.0 | Ethereum, Arbitrum, Polygon, Optimism, Avalanche, Binance, Base, Fantom | bridge |
| LayerZero | 1.0 | Ethereum, Arbitrum, Polygon, Optimism, Avalanche, Binance, Base, Fantom | bridge |

### Oracle Protocols

| Protocol | Version | Chains | Templates |
|----------|---------|--------|-----------|
| Chainlink | 1.0 | Ethereum, Arbitrum, Polygon, Optimism, Avalanche, Binance, Base, Fantom | price_feed |

### Other Protocols

| Protocol | Version | Chains | Templates |
|----------|---------|--------|-----------|
| Lido | 1.0 | Ethereum | staking |
| MakerDAO | 1.0 | Ethereum | vault |

## Adding New Protocols

### Adding a New Protocol to Registry

```python
from defillama_contracts.protocols import ProtocolDefinition, ProtocolType

# Create protocol definition
new_protocol = ProtocolDefinition(
    name="New DEX",
    protocol_type=ProtocolType.DEX,
    chains=["Ethereum", "Arbitrum"],
    contracts={
        "router": ["0x1234..."],
        "factory": ["0x5678..."]
    },
    templates={
        "router": "uniswap_v2_router",  # Use existing template
        "factory": "uniswap_v2_factory"
    },
    version="1.0",
    website="https://newdex.example.com"
)

# Add to registry
registry.protocols["new_dex"] = new_protocol
```

### Creating a New Template

```python
from defillama_contracts.protocols import (
    ProtocolType, ContractRole, ContractMethod, ProtocolTemplate
)

# Create custom template
custom_template = ProtocolTemplate(
    protocol_type=ProtocolType.DEX,
    contract_role=ContractRole.ROUTER,
    standard_interfaces=["ICustomRouter"],
    methods=[
        ContractMethod(
            name="customSwap",
            signature="customSwap(uint256,uint256)",
            inputs=[
                {"name": "amountIn", "type": "uint256"},
                {"name": "minOut", "type": "uint256"}
            ],
            outputs=[{"type": "uint256"}],
            state_mutability="nonpayable",
            description="Execute custom swap",
            category="write",
            gas_estimate=150000
        )
    ]
)

# Add to catalog
catalog.templates["custom_router"] = custom_template
```

## Best Practices

1. **Use Auto-Detection**: Let `ProtocolContract` auto-detect the protocol when possible
2. **Check Role**: Verify the contract role before calling protocol-specific methods
3. **Handle Errors**: Protocol methods may fail if contract doesn't implement expected interface
4. **Gas Estimates**: Use provided gas estimates for transaction planning
5. **Method Signatures**: Use exact method signatures from templates
6. **Chain Awareness**: Always specify chain when looking up protocols or contracts

## Examples

See `examples/06_protocol_catalog.py` for comprehensive examples of using the protocol catalog.

## CLI Reference

```bash
# List all protocols
python -m defillama_contracts.cli_protocols list

# Show protocol details
python -m defillama_contracts.cli_protocols info <protocol> [--methods]

# List templates
python -m defillama_contracts.cli_protocols templates [--type <type>]

# Show template methods
python -m defillama_contracts.cli_protocols methods <template>

# Find protocol by address
python -m defillama_contracts.cli_protocols search <address> --chain <chain>

# Verify contract
python -m defillama_contracts.cli_protocols verify <address> --chain <chain>
```