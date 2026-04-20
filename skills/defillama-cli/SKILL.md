---
name: defillama-cli
category: trading
description: Comprehensive CLI for interacting with the DefiLlama ecosystem - chains, protocols, DEXs, bridges, yields, RPCs, and on-chain operations.
version: 1.0
created: 2026-04-19
author: hermes
tags: [defi, cli, defillama, chains, dexs, bridges, yields, rpcs]
---

# DefiLlama CLI

## Purpose
Unified command-line interface for any AI agent to interact with the DefiLlama ecosystem.
Provides access to chains, protocols, DEXs, bridges, yields, RPCs, core assets, and on-chain operations.

## Installation
```bash
ln -sf ~/.hermes/data/defillama_unified/defillama-cli.py ~/.local/bin/defillama-cli
chmod +x ~/.local/bin/defillama-cli
```

## Commands

### chains - List/search chains
```bash
defillama-cli chains --top 20 --sort dex        # Top 20 by DEX count
defillama-cli chains --search base               # Search chains
defillama-cli chains --json                      # JSON output
defillama-cli --api chains --top 10              # Use live API
```

### chain - Chain details
```bash
defillama-cli chain base --rpcs --dexs --assets  # Full chain info
defillama-cli chain ethereum --json              # JSON output
```

### protocols - List/search protocols
```bash
defillama-cli protocols --chain ethereum --top 10  # Protocols on Ethereum
defillama-cli protocols --category Dexs            # Filter by category
defillama-cli protocols --search uniswap           # Search protocols
defillama-cli --api protocols --top 5              # Live API
```

### protocol - Protocol details
```bash
defillama-cli protocol uniswap-v3                # Show protocol details
defillama-cli protocol aave --json               # JSON output
```

### dexs - List DEXs
```bash
defillama-cli dexs --chain base                  # DEXs on Base
defillama-cli dexs --search uniswap              # Search DEXs
defillama-cli dexs --chain ethereum --json       # JSON output
```

### dex - DEX details
```bash
defillama-cli dex uniswap                        # DEX factory addresses
defillama-cli dex aerodrome --json               # JSON output
```

### bridges - List bridges
```bash
defillama-cli bridges                            # All bridges
defillama-cli bridges --search axelar            # Search bridges
defillama-cli bridges --chain ethereum           # Bridges on Ethereum
```

### yields - Yield opportunities
```bash
defillama-cli --api yields --chain base --min-apy 5 --top 10  # Live API
defillama-cli yields --search aave               # Search yields
```

### rpc - RPC endpoints
```bash
defillama-cli rpc ethereum                       # Get RPCs
defillama-cli rpc base --verify                  # Verify RPCs work
defillama-cli rpc polygon --json                 # JSON output
```

### assets - Core assets
```bash
defillama-cli assets ethereum                    # WETH, USDC, etc.
defillama-cli assets base --json                 # JSON output
```

### quote - Swap quotes
```bash
defillama-cli quote base 0xWETH 0xUSDC --amount 1000000000000000000
```

### search - Search everything
```bash
defillama-cli search uniswap                     # Search chains, protocols, DEXs
defillama-cli search aave --json                 # JSON output
```

### price - DEX price fetching (NEW)
```bash
defillama-cli price --chain Base --token-in 0xWETH --token-out 0xUSDC --amount 1.0
defillama-cli price --chain Base --token-in 0xWETH --token-out 0xUSDC --amount 1.0 --dex uniswapv2
```
Uses PriceFetcher with multi-provider RPC fallback. First available RPC is selected automatically.

### dex - List verified DEX contracts on a chain
```bash
defillama-cli dex --chain Base                   # List all verified DEXes
defillama-cli dex --chain Base --verbose         # Show contract details
```

### db - Direct SQLite database access
```bash
defillama-cli db --chain Base                    # Contracts on Base
defillama-cli db --chain Base --type DEX         # DEX contracts on Base
defillama-cli db --stats                         # Database statistics
defillama-cli db --search uniswap                # Search by protocol name
defillama-cli db --export csv                    # Export to CSV
```
Direct queries against ~/.hermes/data/defillama_verified_contracts.db

### registry - Registry data
```bash
defillama-cli registry                           # List registries
defillama-cli registry uniswapV2 --verbose       # Show registry details
defillama-cli registry compound --json           # JSON output
```

## Data Sources
- Local: 2,437 chains, 1,952 protocols, 546 DEX factories, 86 bridges, 658 yields
- Live API: api.llama.fi/protocols (7,362), api.llama.fi/v2/chains (440)
- Registries: uniswapV2 (717 protocols), uniswapV3 (229), compound (93), aave (60)
- Verified DB: 1,693 contracts (1,308 deployed, 77.3%) across 49 chains
- DEXes: 422/431 verified (97.9%) - highest verification rate
- Bridges+yields: 394/546 verified (72.2%)
- Registries: 1,451/2,901 verified (50.0%)

## Key Files
- CLI: `~/.hermes/data/defillama_unified/defillama-cli.py`
- Module: `~/.hermes/data/defillama_unified/defillama_unified.py`
- Data: `~/.hermes/data/defillama_unified/*.json`

## Pitfalls
- `--limit` and `--json` go BEFORE the subcommand: `defillama-cli --limit 5 --json chains`
- `--api` forces live API, default uses local data when available
- Chain names are case-insensitive and aliased (eth->ethereum, bsc->binance, etc.)
- RPC verification requires `requests` library

## Large-Scale Cross-Chain Verification Pattern (learned)
When scanning thousands of addresses (e.g., registry/factory `eth_getCode` checks across 50+ chains), do NOT rely on a single `execute_code` run.

Use this resilient pattern instead:
1. Keep rolling state in `/tmp/reg_state.json` with:
   - `remaining` addresses
   - `total_deployed`
   - `chain_deployed`
   - `tested_chains`
2. Run small foreground batches first (1-3 chains) to validate throughput and time per chain.
3. If runtime approaches tool timeout (~300s), pivot to a background terminal runner:
   - write a dedicated Python script to `/tmp/run_reg_scan.py`
   - run with `terminal(background=true, notify_on_complete=true)`
   - monitor with `process poll/wait/log`
4. Ensure progress logs flush immediately (`print(..., flush=True)`) or logs may appear empty while process is running.
5. After each chain, atomically rewrite state file so scans can resume after interruption without rework.

Why this matters:
- avoids repeated timeout loss
- supports resumable, long-running chain sweeps
- enables user-requested “keep running” without manual restarts

## Contributing to DefiLlama (Fork PR Workflow)

When creating a PR to DefiLlama repos from a fork:
1. Fork: `mcp_github_fork_repository(owner="DefiLlama", repo="DefiLlama-Adapters")`
2. Branch: `mcp_github_create_branch(branch="feat/...", from_branch="main", owner="YOUR_USERNAME", repo="DefiLlama-Adapters")`
3. Push files: `mcp_github_create_or_update_file(..., branch="feat/...", owner="YOUR_USERNAME", repo="DefiLlama-Adapters")`
4. Create PR: `mcp_github_create_pull_request(head="YOUR_USERNAME:feat/...", base="main", owner="DefiLlama", repo="DefiLlama-Adapters")`

**Critical**: The `head` parameter MUST be `username:branch` format (e.g., `TerexitariusStomp:feat/defillama-cli`), NOT just `branch`. GitHub API returns 422 "Validation Failed" on `head` field if format is wrong.

**Note**: DefiLlama-Adapters PR template is for protocol TVL adapters (JavaScript). CLI tools may be rejected. Consider DefiLlama/dimension-adapters or a dedicated tools repo instead.

## Related Skills
- `defi-infrastructure-aggregation` - Data extraction from DefiLlama repos
- `defi-contract-integration` - On-chain execution with factory addresses
- `universal-contract-classifier` - Auto-classify any contract on-chain (no ABI required)

## Price Fetcher Module

~/.hermes/defillama-contracts/price_fetcher.py

Uses standard UniV2-style router ABIs with multi-provider RPC fallback.
For native ETH, wraps to WETH first, queries pair reserves, then unwraps.

### Price Discovery Finding (Base Chain)
34% price spread discovered across Base DEXes for 100 USDC → WETH:
- Uniswap V2: 0.04367 WETH ($2,289/ETH)
- SushiSwap: 0.04815 WETH ($2,076/ETH)
- BaseSwap: 0.05824 WETH ($1,717/ETH)
Best execution saves 33% vs worst execution!

### Multi-Provider RPC Pattern
```python
from defillama_contracts import DefiLlamaContracts
client = DefiLlamaContracts()
db = client.get_database()
rpcs = db.get_validated_rpcs("Base")
provider = HTTPProvider(rpcs[0])  # First available
```

## Verified Contracts Database

1,693 contracts (1,308 deployed, 77.3%) across 49 chains stored in:
```
~/.hermes/data/defillama_verified_contracts.db
```

### Library CLI Commands

```bash
# Classify any contract (probes on-chain)
python ~/.hermes/defillama-contracts/cli.py classify --chain Ethereum --address 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984

# Get interaction guide with example code
python ~/.hermes/defillama-contracts/cli.py guide --chain Ethereum --address 0x... --code

# Get smart contract wrapper
python ~/.hermes/defillama-contracts/cli.py smart --chain Ethereum --address 0x...
```

### Python API

```python
from defillama_contracts import DefiLlamaContracts

client = DefiLlamaContracts()

# Classify any contract
result = client.classify_contract("Ethereum", "0x...")

# Get smart wrapper (auto-detects protocol)
smart = client.get_smart_contract("Ethereum", "0x...")
smart.call_protocol_method("getPair", [tokenA, tokenB])

# Get interaction guide
guide = client.get_contract_interaction_guide("Ethereum", "0x...")

client.close()
```
